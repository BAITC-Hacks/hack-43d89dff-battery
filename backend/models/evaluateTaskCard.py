"""Deterministic readiness scoring for confirmed business task cards.

The scorer deliberately contains no model calls.  It awards points only for
information present in the supplied card and explains every lost point so a
business can improve the task before (or after) publication.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable


CriterionResult = dict[str, Any]


def evaluate_task_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Score a task card from 0 to 100 using the published product weights."""
    if not isinstance(card, Mapping):
        raise ValueError("card must be a mapping")

    checks: list[tuple[str, str, int, Callable[[Mapping[str, Any]], CriterionResult]]] = [
        ("context_and_business_need", "Context and business need", 20, _context_score),
        ("data_and_materials", "Data and materials", 20, _data_score),
        ("expected_result", "Expected result", 15, _expected_result_score),
        ("success_criteria", "Success criteria", 15, _success_criteria_score),
        ("limitations", "Limitations", 10, _limitations_score),
        ("target_users", "Target users", 10, _target_users_score),
        (
            "contact_and_interaction",
            "Business contact and interaction format",
            10,
            _contact_score,
        ),
    ]

    breakdown = []
    suggestions: list[str] = []
    missing_fields: list[str] = []
    for key, label, maximum, check in checks:
        result = check(card)
        item = {
            "key": key,
            "label": label,
            "score": int(result["score"]),
            "max_score": maximum,
            "explanation": result["explanation"],
            "missing_fields": result["missing_fields"],
            "suggestions": result["suggestions"],
        }
        breakdown.append(item)
        missing_fields.extend(item["missing_fields"])
        suggestions.extend(item["suggestions"])

    score = sum(item["score"] for item in breakdown)
    return {
        "score": score,
        "max_score": 100,
        "readiness_level": readiness_level(score),
        "breakdown": breakdown,
        "missing_information": list(dict.fromkeys(missing_fields)),
        "improvement_suggestions": list(dict.fromkeys(suggestions)),
        "scoring_version": "1.0",
    }


def readiness_level(score: int) -> str:
    """Map a numeric score to the four catalog readiness levels."""
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("score must be an integer between 0 and 100")
    if score < 40:
        return "draft"
    if score < 70:
        return "working"
    if score < 90:
        return "ready"
    return "priority"


def _context_score(card: Mapping[str, Any]) -> CriterionResult:
    context = _text(card.get("context"))
    need = _text(card.get("business_need"))
    score = (10 if context else 0) + (10 if need else 0)
    missing = []
    suggestions = []
    if not context:
        missing.append("context")
        suggestions.append("Describe the current process, situation, or pain point.")
    if not need:
        missing.append("business_need")
        suggestions.append("State why solving the task matters to the business.")
    return _result(score, 20, missing, suggestions)


def _data_score(card: Mapping[str, Any]) -> CriterionResult:
    data = card.get("available_data")
    data = data if isinstance(data, Mapping) else {}
    description = _text(data.get("description"))
    sources = _items(data.get("sources"))
    access = _text(data.get("access_conditions"))
    score = (12 if description else 0) + (4 if sources else 0) + (4 if access else 0)
    missing = []
    suggestions = []
    if not description:
        missing.append("available_data.description")
        suggestions.append("Describe the data, examples, or other materials available to the team.")
    if not sources:
        missing.append("available_data.sources")
        suggestions.append("Name where the materials come from or state explicitly that none are available.")
    if not access:
        missing.append("available_data.access_conditions")
        suggestions.append("Explain access, privacy, anonymization, or sharing conditions.")
    return _result(score, 20, missing, suggestions)


def _expected_result_score(card: Mapping[str, Any]) -> CriterionResult:
    if _text(card.get("expected_result")):
        return _result(15, 15, [], [])
    return _result(
        0,
        15,
        ["expected_result"],
        ["Specify the concrete deliverable the student team should produce."],
    )


def _success_criteria_score(card: Mapping[str, Any]) -> CriterionResult:
    criteria = card.get("success_criteria")
    criteria = criteria if _is_sequence(criteria) else []
    valid = [item for item in criteria if isinstance(item, Mapping) and _text(item.get("metric"))]
    targeted = [item for item in valid if _text(item.get("target"))]
    verifiable = [item for item in targeted if _text(item.get("verification_method"))]
    score = 0
    if valid:
        score += 5
    if targeted:
        score += 7
    if verifiable:
        score += 3
    missing = []
    suggestions = []
    if not valid:
        missing.append("success_criteria.metric")
        suggestions.append("Add at least one measurable success metric.")
    if not targeted:
        missing.append("success_criteria.target")
        suggestions.append("Give the success metric a concrete target value or acceptance threshold.")
    if not verifiable:
        missing.append("success_criteria.verification_method")
        suggestions.append("Explain how the result will be tested or accepted.")
    return _result(score, 15, missing, suggestions)


def _limitations_score(card: Mapping[str, Any]) -> CriterionResult:
    if _items(card.get("limitations")):
        return _result(10, 10, [], [])
    return _result(
        0,
        10,
        ["limitations"],
        ["List time, legal, privacy, technical, budget, or scope constraints; state 'none' if confirmed."],
    )


def _target_users_score(card: Mapping[str, Any]) -> CriterionResult:
    if _items(card.get("target_users")):
        return _result(10, 10, [], [])
    return _result(
        0,
        10,
        ["target_users"],
        ["Identify who will use or benefit from the result."],
    )


def _contact_score(card: Mapping[str, Any]) -> CriterionResult:
    contact = card.get("business_contact")
    contact = contact if isinstance(contact, Mapping) else {}
    interaction = card.get("interaction_format")
    interaction = interaction if isinstance(interaction, Mapping) else {}
    has_contact = bool(_text(contact.get("name")) or _text(contact.get("email")))
    has_role = bool(_text(contact.get("role")))
    has_channel = bool(_text(interaction.get("channel")))
    has_cadence = bool(
        _text(interaction.get("frequency")) or _text(interaction.get("feedback_process"))
    )
    score = (3 if has_contact else 0) + (2 if has_role else 0)
    score += (3 if has_channel else 0) + (2 if has_cadence else 0)
    missing = []
    suggestions = []
    if not has_contact:
        missing.append("business_contact.name_or_email")
        suggestions.append("Add a named business contact or contact email.")
    if not has_role:
        missing.append("business_contact.role")
        suggestions.append("Add the business contact's role in the project.")
    if not has_channel:
        missing.append("interaction_format.channel")
        suggestions.append("Choose a communication channel for the student team.")
    if not has_cadence:
        missing.append("interaction_format.frequency_or_feedback_process")
        suggestions.append("Set a consultation cadence or feedback process.")
    return _result(score, 10, missing, suggestions)


def _result(
    score: int,
    maximum: int,
    missing_fields: list[str],
    suggestions: list[str],
) -> CriterionResult:
    if score == maximum:
        explanation = "Complete: all readiness information for this area is present."
    elif score:
        explanation = f"Partially complete: {score} of {maximum} points awarded."
    else:
        explanation = "Not ready: required information for this area is missing."
    return {
        "score": score,
        "explanation": explanation,
        "missing_fields": missing_fields,
        "suggestions": suggestions,
    }


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


def _items(value: Any) -> list[Any]:
    if not _is_sequence(value):
        return []
    return [item for item in value if item not in (None, "", [], {})]


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
