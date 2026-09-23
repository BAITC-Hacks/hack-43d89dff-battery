"""Source-grounded business task-card generation.

The module accepts a business draft, question-answer pairs, and a summary.
It can call an injected LLM, but has a deterministic fallback so the MVP works
without an external provider. Unknown facts remain empty rather than invented.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

TaskCard = dict[str, Any]
LLMGenerate = Callable[[str], str | Mapping[str, Any]]

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
Do not calculate rating or workflow status.

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
    Omitting it uses a conservative deterministic fallback.
    """
    normalized_input = _normalize_input(payload)

    if llm_generate is None:
        raw_card = _deterministic_fallback(normalized_input)
        generated_by = "deterministic_fallback"
    else:
        raw_card = _parse_llm_response(llm_generate(build_task_card_prompt(normalized_input)))
        generated_by = "llm"

    card = _normalize_card(raw_card)
    card["generation_metadata"]["generated_by"] = generated_by
    card["generation_metadata"]["requires_human_confirmation"] = True
    card["missing_information"] = _missing_rating_fields(card)
    return card


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
