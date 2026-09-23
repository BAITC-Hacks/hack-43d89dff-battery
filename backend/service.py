"""Application service for the task-card marketplace workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .database import Database
from .models.evaluateTaskCard import evaluate_task_card
from .models.generateQuestions import generate_questions, generate_questions_offline
from .models.generateTaskCard import (
    _get_openai_api_key,
    _normalize_card,
    generate_task_card,
    generate_task_card_offline,
)


QuestionGenerator = Callable[[str], list[str]]
CardGenerator = Callable[[Mapping[str, Any]], dict[str, Any]]

EDITABLE_CARD_FIELDS = {
    "title",
    "context",
    "business_need",
    "target_users",
    "required_skills",
    "available_data",
    "limitations",
    "expected_result",
    "success_criteria",
    "business_contact",
    "interaction_format",
    "industry",
    "tags",
}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class MarketplaceService:
    def __init__(
        self,
        database: Database,
        *,
        question_generator: QuestionGenerator | None = None,
        card_generator: CardGenerator | None = None,
        ai_mode: str | None = None,
    ) -> None:
        self.database = database
        self.question_generator = question_generator
        self.card_generator = card_generator
        self.ai_mode = (ai_mode or os.getenv("MARKETPLACE_AI_MODE", "auto")).lower()
        if self.ai_mode not in {"auto", "online", "offline"}:
            raise ValueError("MARKETPLACE_AI_MODE must be auto, online, or offline")

    def initialize(self) -> None:
        self.database.initialize()

    def create_business(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = _required_text(payload, "name", maximum=160)
        description = _optional_text(payload.get("description"), maximum=2000)
        contact_name = _optional_text(payload.get("contact_name"), maximum=160)
        contact_email = _optional_email(payload.get("contact_email"))
        business_id = _id("biz")
        owner_token = secrets.token_urlsafe(32)
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO businesses
                (id, name, description, contact_name, contact_email, owner_token_hash)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    business_id,
                    name,
                    description,
                    contact_name,
                    contact_email,
                    _token_hash(owner_token),
                ),
            )
            row = connection.execute(
                "SELECT * FROM businesses WHERE id = ?", (business_id,)
            ).fetchone()
        result = _business_view(row)
        result["owner_token"] = owner_token
        result["owner_token_notice"] = "Save this token; it is shown only in this response."
        return result

    def create_team(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = _required_text(payload, "name", maximum=160)
        description = _optional_text(payload.get("description"), maximum=2000)
        skills = _string_list(payload.get("skills", []), "skills", maximum_items=30)
        contact_email = _required_email(payload, "contact_email")
        team_id = _id("team")
        owner_token = secrets.token_urlsafe(32)
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO teams
                (id, name, description, skills_json, contact_email, owner_token_hash)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    team_id,
                    name,
                    description,
                    _dump(skills),
                    contact_email,
                    _token_hash(owner_token),
                ),
            )
            row = connection.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        result = _team_view(row)
        result["owner_token"] = owner_token
        result["owner_token_notice"] = "Save this token; it is shown only in this response."
        return result

    def create_task(
        self,
        payload: Mapping[str, Any],
        owner_token: str | None,
    ) -> dict[str, Any]:
        business_id = _required_text(payload, "business_id", maximum=80)
        initial_draft = _required_text(payload, "initial_draft", maximum=12000)
        with self.database.read() as connection:
            business = self._require_business_owner(connection, business_id, owner_token)
        try:
            questions = self._questions(initial_draft)
        except (ValueError, RuntimeError) as error:
            raise ServiceError(502, "question_generation_failed", str(error)) from error

        task_id = _id("task")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO tasks
                (id, business_id, initial_draft, questions_json, status)
                VALUES (?, ?, ?, ?, 'awaiting_answers')""",
                (task_id, business["id"], initial_draft, _dump(questions)),
            )
            row = self._task_row(connection, task_id)
        return _task_view(row, include_private=True)

    def submit_answers(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        owner_token: str | None,
    ) -> dict[str, Any]:
        with self.database.read() as connection:
            row = self._task_row(connection, task_id)
            self._require_business_owner(connection, row["business_id"], owner_token)
        if row["status"] == "published":
            raise ServiceError(409, "task_already_published", "Published tasks cannot be regenerated.")

        answers = payload.get("answers")
        if not _is_list(answers):
            raise ServiceError(422, "invalid_answers", "answers must be a JSON list")
        task_summary = _optional_text(payload.get("task_summary"), maximum=5000)
        generation_input = {
            "initial_draft": row["initial_draft"],
            "clarifying_questions": _load(row["questions_json"], []),
            "answers": answers,
            "task_summary": task_summary,
        }
        try:
            card = self._card(generation_input)
        except ValueError as error:
            raise ServiceError(422, "invalid_answers", str(error)) from error
        except RuntimeError as error:
            raise ServiceError(502, "task_card_generation_failed", str(error)) from error
        # Providers and injected test generators are not trusted to return the
        # full storage contract. Normalize at the application boundary before
        # scoring or persisting the card.
        card = _normalize_card(card)
        evaluation = evaluate_task_card(card)
        card["missing_information"] = list(
            dict.fromkeys(card["missing_information"] + evaluation["missing_information"])
        )

        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE tasks SET answers_json = ?, task_summary = ?, card_json = ?,
                evaluation_json = ?, status = 'card_ready', confirmed_at = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (_dump(answers), task_summary, _dump(card), _dump(evaluation), task_id),
            )
            updated = self._task_row(connection, task_id)
        return _task_view(updated, include_private=True)

    def update_card(
        self,
        task_id: str,
        changes: Mapping[str, Any],
        owner_token: str | None,
    ) -> dict[str, Any]:
        if not isinstance(changes, Mapping) or not changes:
            raise ServiceError(422, "invalid_card_update", "Provide at least one card field to update.")
        unknown = set(changes) - EDITABLE_CARD_FIELDS
        if unknown:
            raise ServiceError(
                422,
                "invalid_card_fields",
                "Unknown or protected card fields: " + ", ".join(sorted(unknown)),
            )
        with self.database.read() as connection:
            row = self._task_row(connection, task_id)
            self._require_business_owner(connection, row["business_id"], owner_token)
        if row["status"] == "published":
            raise ServiceError(409, "task_already_published", "Published task cards cannot be edited.")
        if not row["card_json"]:
            raise ServiceError(409, "card_not_generated", "Submit clarification answers first.")

        card = _load(row["card_json"], {})
        for field, value in changes.items():
            if field in {"available_data", "business_contact", "interaction_format"}:
                if not isinstance(value, Mapping):
                    raise ServiceError(422, "invalid_card_update", f"{field} must be an object")
                card[field] = {**card.get(field, {}), **value}
            else:
                card[field] = value
        card = _normalize_card(card)
        evaluation = evaluate_task_card(card)
        card["missing_information"] = evaluation["missing_information"]
        card["generation_metadata"]["requires_human_confirmation"] = True

        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE tasks SET card_json = ?, evaluation_json = ?, status = 'card_ready',
                confirmed_at = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (_dump(card), _dump(evaluation), task_id),
            )
            updated = self._task_row(connection, task_id)
        return _task_view(updated, include_private=True)

    def confirm_task(self, task_id: str, owner_token: str | None) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = self._task_row(connection, task_id)
            self._require_business_owner(connection, row["business_id"], owner_token)
            if row["status"] == "published":
                raise ServiceError(409, "task_already_published", "The task is already published.")
            if not row["card_json"]:
                raise ServiceError(409, "card_not_generated", "Submit clarification answers first.")
            card = _load(row["card_json"], {})
            card.setdefault("generation_metadata", {})["requires_human_confirmation"] = False
            evaluation = evaluate_task_card(card)
            connection.execute(
                """UPDATE tasks SET card_json = ?, evaluation_json = ?, status = 'confirmed',
                confirmed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (_dump(card), _dump(evaluation), task_id),
            )
            updated = self._task_row(connection, task_id)
        return _task_view(updated, include_private=True)

    def publish_task(self, task_id: str, owner_token: str | None) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = self._task_row(connection, task_id)
            self._require_business_owner(connection, row["business_id"], owner_token)
            if row["status"] == "published":
                return _task_view(row, include_private=True)
            if row["status"] != "confirmed":
                raise ServiceError(409, "confirmation_required", "Confirm the current task card first.")
            card = _load(row["card_json"], {})
            evaluation = evaluate_task_card(card)
            connection.execute(
                """UPDATE tasks SET evaluation_json = ?, status = 'published',
                published_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (_dump(evaluation), task_id),
            )
            updated = self._task_row(connection, task_id)
        return _task_view(updated, include_private=True)

    def get_task(self, task_id: str, owner_token: str | None = None) -> dict[str, Any]:
        with self.database.read() as connection:
            row = self._task_row(connection, task_id)
            is_owner = self._is_business_owner(connection, row["business_id"], owner_token)
        if row["status"] != "published" and not is_owner:
            raise ServiceError(404, "task_not_found", "Task not found.")
        return _task_view(row, include_private=is_owner)

    def list_business_tasks(self, business_id: str, owner_token: str | None) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            self._require_business_owner(connection, business_id, owner_token)
            rows = connection.execute(
                "SELECT * FROM tasks WHERE business_id = ? ORDER BY created_at DESC", (business_id,)
            ).fetchall()
        return [_task_view(row, include_private=True) for row in rows]

    def catalog(
        self,
        *,
        tags: Sequence[str] = (),
        industry: str | None = None,
        readiness: str | None = None,
        minimum_score: int = 0,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if readiness and readiness not in {"draft", "working", "ready", "priority"}:
            raise ServiceError(422, "invalid_readiness", "Unknown readiness level.")
        if not 0 <= minimum_score <= 100:
            raise ServiceError(422, "invalid_minimum_score", "minimum_score must be 0-100.")
        requested_tags = {item.casefold() for item in tags if _optional_text(item, maximum=80)}
        industry_key = industry.casefold() if industry else None
        query_key = query.casefold() if query else None
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))

        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT tasks.*, businesses.name AS business_name
                FROM tasks JOIN businesses ON businesses.id = tasks.business_id
                WHERE tasks.status = 'published'"""
            ).fetchall()
        matched = []
        for row in rows:
            item = _task_view(row, include_private=False)
            card = item.get("card") or {}
            evaluation = item.get("evaluation") or {}
            card_tags = {tag.casefold() for tag in card.get("tags", []) if isinstance(tag, str)}
            if requested_tags and not requested_tags.issubset(card_tags):
                continue
            if industry_key and str(card.get("industry") or "").casefold() != industry_key:
                continue
            if readiness and evaluation.get("readiness_level") != readiness:
                continue
            if int(evaluation.get("score", 0)) < minimum_score:
                continue
            searchable = " ".join(
                str(card.get(field) or "")
                for field in ("title", "context", "business_need", "expected_result", "industry")
            ) + " " + " ".join(card.get("tags", []))
            if query_key and query_key not in searchable.casefold():
                continue
            matched.append(item)
        matched.sort(
            key=lambda item: (
                int((item.get("evaluation") or {}).get("score", 0)),
                item.get("published_at") or "",
            ),
            reverse=True,
        )
        return {
            "items": matched[offset : offset + limit],
            "total": len(matched),
            "limit": limit,
            "offset": offset,
        }

    def create_proposal(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        owner_token: str | None,
    ) -> dict[str, Any]:
        team_id = _required_text(payload, "team_id", maximum=80)
        message = _required_text(payload, "message", maximum=5000)
        approach = _required_text(payload, "approach", maximum=8000)
        timeline = _optional_text(payload.get("estimated_timeline"), maximum=500)
        links = _string_list(payload.get("portfolio_links", []), "portfolio_links", maximum_items=10)
        with self.database.transaction() as connection:
            task = self._task_row(connection, task_id)
            if task["status"] != "published":
                raise ServiceError(404, "task_not_found", "Published task not found.")
            self._require_team_owner(connection, team_id, owner_token)
            proposal_id = _id("prop")
            try:
                connection.execute(
                    """INSERT INTO proposals
                    (id, task_id, team_id, message, approach, estimated_timeline, portfolio_links_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (proposal_id, task_id, team_id, message, approach, timeline, _dump(links)),
                )
            except sqlite3.IntegrityError as error:
                raise ServiceError(
                    409, "proposal_already_exists", "This team has already proposed for the task."
                ) from error
            row = self._proposal_row(connection, proposal_id)
        return _proposal_view(row, include_team=False)

    def list_task_proposals(self, task_id: str, owner_token: str | None) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            task = self._task_row(connection, task_id)
            self._require_business_owner(connection, task["business_id"], owner_token)
            rows = connection.execute(
                """SELECT proposals.*, teams.name AS team_name, teams.description AS team_description,
                teams.skills_json AS team_skills_json, teams.contact_email AS team_contact_email
                FROM proposals JOIN teams ON teams.id = proposals.team_id
                WHERE proposals.task_id = ? ORDER BY proposals.created_at DESC""",
                (task_id,),
            ).fetchall()
        return [_proposal_view(row, include_team=True) for row in rows]

    def list_team_proposals(self, team_id: str, owner_token: str | None) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            self._require_team_owner(connection, team_id, owner_token)
            rows = connection.execute(
                """SELECT proposals.* FROM proposals WHERE team_id = ?
                ORDER BY created_at DESC""",
                (team_id,),
            ).fetchall()
        return [_proposal_view(row, include_team=False) for row in rows]

    def decide_proposal(
        self,
        proposal_id: str,
        decision: str,
        owner_token: str | None,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected"}:
            raise ServiceError(422, "invalid_decision", "decision must be accepted or rejected")
        with self.database.transaction() as connection:
            proposal = self._proposal_row(connection, proposal_id)
            task = self._task_row(connection, proposal["task_id"])
            self._require_business_owner(connection, task["business_id"], owner_token)
            if proposal["status"] != "submitted":
                raise ServiceError(409, "proposal_already_decided", "Proposal has already been decided.")
            if decision == "accepted":
                accepted = connection.execute(
                    "SELECT id FROM proposals WHERE task_id = ? AND status = 'accepted'",
                    (proposal["task_id"],),
                ).fetchone()
                if accepted:
                    raise ServiceError(
                        409, "task_already_has_team", "Another proposal is already accepted for this task."
                    )
            try:
                connection.execute(
                    """UPDATE proposals SET status = ?,
                    decided_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                    (decision, proposal_id),
                )
            except sqlite3.IntegrityError as error:
                # The partial unique index is the final concurrency guard when
                # two business decisions race to accept different proposals.
                if decision == "accepted":
                    raise ServiceError(
                        409, "task_already_has_team", "Another proposal is already accepted for this task."
                    ) from error
                raise
            updated = self._proposal_row(connection, proposal_id)
        return _proposal_view(updated, include_team=False)

    def _questions(self, draft: str) -> list[str]:
        if self.question_generator:
            questions = self.question_generator(draft)
            return _validated_questions(questions)
        if self._use_online_ai():
            return generate_questions(draft)
        return generate_questions_offline(draft)

    def _card(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.card_generator:
            card = self.card_generator(payload)
            if not isinstance(card, Mapping):
                raise ValueError("card generator must return a mapping")
            return dict(card)
        if self._use_online_ai():
            return generate_task_card(payload)
        return generate_task_card_offline(payload)

    def _use_online_ai(self) -> bool:
        if self.ai_mode == "online":
            return True
        if self.ai_mode == "offline":
            return False
        try:
            _get_openai_api_key()
            return True
        except RuntimeError:
            return False

    def _task_row(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise ServiceError(404, "task_not_found", "Task not found.")
        return row

    def _proposal_row(self, connection: sqlite3.Connection, proposal_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        if not row:
            raise ServiceError(404, "proposal_not_found", "Proposal not found.")
        return row

    def _require_business_owner(
        self, connection: sqlite3.Connection, business_id: str, owner_token: str | None
    ) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if not row:
            raise ServiceError(404, "business_not_found", "Business not found.")
        if not _token_matches(owner_token, row["owner_token_hash"]):
            raise ServiceError(403, "forbidden", "A valid business owner token is required.")
        return row

    def _is_business_owner(
        self, connection: sqlite3.Connection, business_id: str, owner_token: str | None
    ) -> bool:
        row = connection.execute(
            "SELECT owner_token_hash FROM businesses WHERE id = ?", (business_id,)
        ).fetchone()
        return bool(row and _token_matches(owner_token, row["owner_token_hash"]))

    def _require_team_owner(
        self, connection: sqlite3.Connection, team_id: str, owner_token: str | None
    ) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not row:
            raise ServiceError(404, "team_not_found", "Team not found.")
        if not _token_matches(owner_token, row["owner_token_hash"]):
            raise ServiceError(403, "forbidden", "A valid team owner token is required.")
        return row


def _business_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "contact_name": row["contact_name"],
        "contact_email": row["contact_email"],
        "created_at": row["created_at"],
    }


def _team_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "skills": _load(row["skills_json"], []),
        "contact_email": row["contact_email"],
        "created_at": row["created_at"],
    }


def _task_view(row: sqlite3.Row, *, include_private: bool) -> dict[str, Any]:
    keys = set(row.keys())
    result = {
        "id": row["id"],
        "business_id": row["business_id"],
        "business_name": row["business_name"] if "business_name" in keys else None,
        "status": row["status"],
        "card": _load(row["card_json"], None),
        "evaluation": _load(row["evaluation_json"], None),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "published_at": row["published_at"],
    }
    if include_private:
        result.update(
            {
                "initial_draft": row["initial_draft"],
                "clarifying_questions": _load(row["questions_json"], []),
                "answers": _load(row["answers_json"], []),
                "task_summary": row["task_summary"],
                "confirmed_at": row["confirmed_at"],
            }
        )
    return result


def _proposal_view(row: sqlite3.Row, *, include_team: bool) -> dict[str, Any]:
    keys = set(row.keys())
    result = {
        "id": row["id"],
        "task_id": row["task_id"],
        "team_id": row["team_id"],
        "message": row["message"],
        "approach": row["approach"],
        "estimated_timeline": row["estimated_timeline"],
        "portfolio_links": _load(row["portfolio_links_json"], []),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "decided_at": row["decided_at"],
    }
    if include_team and "team_name" in keys:
        result["team"] = {
            "id": row["team_id"],
            "name": row["team_name"],
            "description": row["team_description"],
            "skills": _load(row["team_skills_json"], []),
            "contact_email": row["team_contact_email"],
        }
    return result


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_matches(token: str | None, stored_hash: str) -> bool:
    return bool(token and hmac.compare_digest(_token_hash(token), stored_hash))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def _required_text(payload: Mapping[str, Any], field: str, *, maximum: int) -> str:
    value = _optional_text(payload.get(field), maximum=maximum)
    if not value:
        raise ServiceError(422, "validation_error", f"{field} is required")
    return value


def _optional_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError(422, "validation_error", "Text fields must be strings.")
    value = " ".join(value.split()).strip()
    if not value:
        return None
    if len(value) > maximum:
        raise ServiceError(422, "validation_error", f"Text exceeds {maximum} characters.")
    return value


def _required_email(payload: Mapping[str, Any], field: str) -> str:
    email = _optional_email(payload.get(field))
    if not email:
        raise ServiceError(422, "validation_error", f"{field} is required")
    return email


def _optional_email(value: Any) -> str | None:
    email = _optional_text(value, maximum=320)
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        raise ServiceError(422, "validation_error", "Invalid email address.")
    return email


def _string_list(value: Any, field: str, *, maximum_items: int) -> list[str]:
    if not _is_list(value):
        raise ServiceError(422, "validation_error", f"{field} must be a list")
    if len(value) > maximum_items:
        raise ServiceError(422, "validation_error", f"{field} has too many items")
    result = []
    for item in value:
        text = _optional_text(item, maximum=500)
        if text:
            result.append(text)
    return result


def _is_list(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _validated_questions(value: Any) -> list[str]:
    """Validate custom question-generator output before storing it as JSON."""
    if not _is_list(value):
        raise ValueError("question generator must return a list of questions")
    questions = []
    for item in value:
        question = _optional_text(item, maximum=1000)
        if question and question not in questions:
            questions.append(question)
    if len(questions) < 3:
        raise ValueError("question generator returned fewer than three questions")
    return questions[:7]
