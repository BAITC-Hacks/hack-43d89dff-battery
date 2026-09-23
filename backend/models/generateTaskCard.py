"""Source-grounded business task-card generation.

The module accepts a business draft, question-answer pairs, and a summary.
It supports both OpenAI generation and an explicit deterministic offline mode.
Unknown facts remain empty rather than invented.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TaskCard = dict[str, Any]
LLMGenerate = Callable[[str], str | Mapping[str, Any]]

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

TASK_CARD_SYSTEM_PROMPT = """You are a careful business analyst generating a task card for a student-project marketplace.

Your job is structured extraction, not creative writing. Use only facts in the
provided source material. Answers to clarification questions override the
initial draft, and the initial draft overrides the task summary. Do not invent
facts, contacts, numbers, metrics, deadlines, data, technologies, or skills.
When information is absent, return null or [] and list the field in
missing_information. Do not calculate a rating, choose a team, publish a task,
or create workflow timestamps. Preserve the source language. Return JSON only.

Field rules:
- Always create a concise title from the task summary or initial draft when either is present.
- Always populate context from the current situation described in the initial draft.
- Put the business problem in business_need and the concrete deliverable in expected_result.
- Convert every measurable target from the answers into success_criteria with metric and target.
- Generate 3 to 8 concise tags for catalog filtering from the task's domain, users,
  data, technologies, and implementation focus. Tags may be normalized keywords,
  but must be supported by the source material and must not be invented.
- Only leave a field empty when the source material truly does not contain that information."""


TASK_CARD_TEMPLATE: TaskCard = {
    "title": None,
    "context": None,
    "business_need": None,
    "target_users": [],
    "required_skills": [],
    "available_data": {"description": None, "sources": [], "access_conditions": None},
    "limitations": [],
    "expected_result": None,
    "success_criteria": [],
    "business_contact": {"name": None, "role": None, "email": None},
    "interaction_format": {"channel": None, "frequency": None, "feedback_process": None},
    "industry": None,
    "tags": [],
    "missing_information": [],
    "warnings": [],
    "source_mapping": {},
    "generation_metadata": {"generated_by": None, "requires_human_confirmation": True},
}

# These fields drive the readiness score in the hackathon requirements.
RATING_FIELDS = (
    "context", "business_need", "target_users", "available_data", "limitations",
    "expected_result", "success_criteria", "business_contact", "interaction_format",
)


def build_task_card_prompt(payload: Mapping[str, Any]) -> str:
    """Build a strict, provider-neutral prompt for a task-card LLM."""
    source = json.dumps(_normalize_input(payload), ensure_ascii=False, indent=2)
    schema = json.dumps(TASK_CARD_TEMPLATE, ensure_ascii=False, indent=2)
    return f"""You convert business-task information into an editable task card.

Use only the source material below. Question answers take precedence over the
initial draft, which takes precedence over the generated task summary.
Never invent facts, numbers, contacts, datasets, deadlines, technologies, or
success targets. Use null or [] for unknown fields and list their field names in
missing_information. If sources conflict, preserve the answer and add a warning.
source_mapping maps each populated field to source IDs, such as answer_1.
Do not calculate rating or workflow status. Generate 3 to 8 concise tags from
the task's domain, users, data, technologies, and implementation focus for
catalog filtering. Tags must be supported by the source material.

Before returning JSON, check that the initial draft produced context, the task
summary or draft produced a title, and every measurable answer was considered
for success_criteria. Generate tags even when the business did not explicitly
provide a tag list: derive them from the task content for catalog filtering.
Do not omit a field merely because it needs human review.

Return JSON only with this exact shape:
{schema}

Source material:
{source}
"""


def generate_task_card(
    payload: Mapping[str, Any],
    llm_generate: LLMGenerate | None = None,
) -> TaskCard:
    """Return a complete, human-reviewable task card.

    llm_generate accepts a prompt and returns a JSON string or mapping.
    Omitting it calls the configured OpenAI Responses API integration. Use
    ``generate_task_card_offline`` when an intentionally offline card is needed.
    """
    normalized_input = _normalize_input(payload)

    if llm_generate is None:
        llm_generate = openai_llm_generate

    raw_card = _parse_llm_response(llm_generate(build_task_card_prompt(normalized_input)))
    generated_by = "openai" if llm_generate is openai_llm_generate else "llm"

    card = _normalize_card(raw_card)
    card["generation_metadata"]["generated_by"] = generated_by
    card["generation_metadata"]["requires_human_confirmation"] = True
    card["missing_information"] = list(
        dict.fromkeys(card["missing_information"] + _missing_rating_fields(card))
    )
    return card


def generate_task_card_offline(payload: Mapping[str, Any]) -> TaskCard:
    """Build a conservative card without a network call for demos and tests."""
    normalized_input = _normalize_input(payload)
    card = _normalize_card(_deterministic_fallback(normalized_input))
    card["generation_metadata"]["generated_by"] = "deterministic_offline"
    card["generation_metadata"]["requires_human_confirmation"] = True
    card["missing_information"] = list(
        dict.fromkeys(card["missing_information"] + _missing_rating_fields(card))
    )
    return card


def openai_llm_generate(prompt: str, *, model: str | None = None, timeout: int = 30) -> str:
    """Call the OpenAI Responses API and return its JSON text output."""
    api_key = _get_openai_api_key()
    selected_model = model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    request_body = {
        "model": selected_model,
        "store": False,
        "input": [
            {"role": "developer", "content": TASK_CARD_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 2500,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenAI request failed with HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError("Could not reach the OpenAI API.") from error

    return _extract_openai_output_text(response_body)


def _get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY") or _read_dotenv_value("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to .env or export it in the environment.")
    return api_key


def _read_dotenv_value(name: str) -> str | None:
    """Read one local .env variable without adding a dotenv package dependency."""
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv_path.is_file():
        return None

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'") or None
    return None


def _extract_openai_output_text(response_body: Mapping[str, Any]) -> str:
    """Extract text from a completed Responses API response or raise safely."""
    if response_body.get("status") != "completed":
        raise RuntimeError("OpenAI did not complete the task-card response.")

    for output_item in response_body.get("output", []):
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "refusal":
                raise RuntimeError("OpenAI refused to generate the task card.")
            if content_item.get("type") == "output_text" and content_item.get("text"):
                return content_item["text"]
    raise RuntimeError("OpenAI returned no text for the task card.")



def _normalize_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    initial_draft = _clean_text(payload.get("initial_draft"))
    if not initial_draft:
        raise ValueError("initial_draft is required and cannot be empty")

    questions = payload.get("clarifying_questions", [])
    if not _is_list(questions):
        raise ValueError("clarifying_questions must be a list")
    cleaned_questions = [_clean_text(item) for item in questions]
    if any(question is None for question in cleaned_questions):
        raise ValueError("clarifying_questions cannot contain empty values")
    if len(cleaned_questions) < 3:
        raise ValueError("at least three clarifying_questions are required")

    answers = payload.get("answers", [])
    if not _is_list(answers):
        raise ValueError("answers must be a list")

    pairs: list[dict[str, str]] = []
    for index, item in enumerate(answers):
        if isinstance(item, Mapping):
            question = _clean_text(item.get("question"))
            answer = _clean_text(item.get("answer"))
        else:
            question = cleaned_questions[index] if index < len(cleaned_questions) else None
            answer = _clean_text(item)

        if not answer:
            continue
        if not question:
            raise ValueError("every answer needs an associated question")
        pairs.append({"id": f"answer_{len(pairs) + 1}", "question": question, "answer": answer})

    if len(pairs) < 3:
        raise ValueError("answers for at least three clarifying questions are required")

    return {
        "initial_draft": initial_draft,
        "clarifying_questions": cleaned_questions,
        "answers": pairs,
        "task_summary": _clean_text(payload.get("task_summary")),
    }


def _deterministic_fallback(payload: Mapping[str, Any]) -> TaskCard:
    """Use only direct source facts when a live LLM is unavailable."""
    card = deepcopy(TASK_CARD_TEMPLATE)
    card["context"] = payload["initial_draft"]
    card["source_mapping"]["context"] = ["initial_draft"]

    card["title"] = _first_sentence(payload["initial_draft"])[:120]
    card["business_need"] = payload["initial_draft"]
    card["source_mapping"]["title"] = ["initial_draft"]
    card["source_mapping"]["business_need"] = ["initial_draft"]

    summary = payload.get("task_summary")
    if summary:
        card["title"] = _first_sentence(summary)[:120]
        card["business_need"] = summary
        card["source_mapping"]["title"] = ["task_summary"]
        card["source_mapping"]["business_need"] = ["task_summary"]

    for pair in payload["answers"]:
        question, answer, source_id = pair["question"].lower(), pair["answer"], pair["id"]

        if _has_keyword(question, "user", "who", "for whom", "audience", "пользоват", "пайдалан", "кім"):
            card["target_users"] = _split_values(answer)
            card["source_mapping"]["target_users"] = [source_id]
        elif _has_keyword(question, "data", "dataset", "material", "source", "example", "данн", "дерек", "мәлімет"):
            card["available_data"]["description"] = answer
            card["source_mapping"]["available_data"] = [source_id]
        elif _has_keyword(question, "constraint", "limitation", "deadline", "time", "security", "privacy", "access", "огранич", "срок", "шектеу", "мерзім", "қауіпсіз"):
            card["limitations"].append(answer)
            card["source_mapping"].setdefault("limitations", []).append(source_id)
        elif _has_keyword(question, "success", "metric", "measure", "criteria", "acceptance", "успех", "критер", "өлшем", "табыст"):
            card["success_criteria"].append(
                {"metric": pair["question"], "target": answer, "verification_method": None}
            )
            card["source_mapping"].setdefault("success_criteria", []).append(source_id)
        elif _has_keyword(question, "result", "deliverable", "build", "output", "результ", "нәтиже"):
            card["expected_result"] = answer
            card["source_mapping"]["expected_result"] = [source_id]
        elif _has_keyword(question, "contact", "communication", "meeting", "feedback", "consultation", "контакт", "связ", "байланыс", "кері"):
            card["interaction_format"]["feedback_process"] = answer
            card["source_mapping"]["interaction_format"] = [source_id]
        elif _has_keyword(question, "skill", "technology", "tech stack", "навык", "технолог", "дағды"):
            card["required_skills"] = _split_values(answer)
            card["source_mapping"]["required_skills"] = [source_id]

    return card


def _normalize_card(raw_card: Mapping[str, Any]) -> TaskCard:
    if not isinstance(raw_card, Mapping):
        raise ValueError("task-card response must be a JSON object")

    card = deepcopy(TASK_CARD_TEMPLATE)
    for key in card:
        if key in raw_card:
            card[key] = raw_card[key]

    for field in ("title", "context", "business_need", "expected_result", "industry"):
        card[field] = _clean_text(card[field])
    for field in ("target_users", "required_skills", "limitations", "tags", "warnings"):
        card[field] = _clean_list(card[field])

    card["available_data"] = _normalize_nested(card["available_data"], TASK_CARD_TEMPLATE["available_data"])
    card["business_contact"] = _normalize_nested(card["business_contact"], TASK_CARD_TEMPLATE["business_contact"])
    card["interaction_format"] = _normalize_nested(card["interaction_format"], TASK_CARD_TEMPLATE["interaction_format"])
    card["success_criteria"] = _normalize_success_criteria(card["success_criteria"])
    card["source_mapping"] = _normalize_source_mapping(card["source_mapping"])
    card["generation_metadata"] = _normalize_nested(
        card["generation_metadata"], TASK_CARD_TEMPLATE["generation_metadata"]
    )
    return card


def _missing_rating_fields(card: Mapping[str, Any]) -> list[str]:
    return [field for field in RATING_FIELDS if not _has_value(card[field])]


def _parse_llm_response(response: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    if not isinstance(response, str):
        raise ValueError("llm_generate must return a JSON string or mapping")

    response = response.strip()
    fenced = re.fullmatch(r"[\x60]{3}(?:json)?\s*(.*?)\s*[\x60]{3}", response, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        response = fenced.group(1)
    try:
        result = json.loads(response)
    except json.JSONDecodeError as error:
        raise ValueError("LLM returned invalid JSON") from error
    if not isinstance(result, Mapping):
        raise ValueError("LLM JSON response must be an object")
    return result


def _normalize_nested(value: Any, template: Mapping[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    result = dict(template)
    for key in result:
        if key in source:
            result[key] = source[key]
        if isinstance(result[key], list):
            result[key] = _clean_list(result[key])
        elif not isinstance(result[key], bool):
            result[key] = _clean_text(result[key])
    return result


def _normalize_success_criteria(value: Any) -> list[dict[str, str | None]]:
    if not _is_list(value):
        return []
    result = []
    for item in value:
        if isinstance(item, Mapping):
            criterion = {
                "metric": _clean_text(item.get("metric")),
                "target": _clean_text(item.get("target")),
                "verification_method": _clean_text(item.get("verification_method")),
            }
            if _has_value(criterion):
                result.append(criterion)
    return result


def _normalize_source_mapping(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for field, source_ids in value.items():
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        cleaned = _clean_list(source_ids)
        if cleaned:
            result[str(field)] = cleaned
    return result


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


def _clean_list(value: Any) -> list[str]:
    if not _is_list(value):
        return []
    return [cleaned for item in value if (cleaned := _clean_text(item))]


def _is_list(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str)


def _split_values(value: str) -> list[str]:
    return [item.strip(" -•") for item in re.split(r"[,;\n]", value) if item.strip(" -•")]


def _has_keyword(question: str, *keywords: str) -> bool:
    return any(keyword in question for keyword in keywords)


def _first_sentence(text: str) -> str:
    return re.split(r"[.!?]", text, maxsplit=1)[0].strip() or text


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_value(item) for item in value.values())
    return bool(value)
