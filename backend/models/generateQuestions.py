"""Clarification-question generation for rough business task drafts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .generateTaskCard import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_RESPONSES_URL,
    _extract_openai_output_text,
    _get_openai_api_key,
)


LLMGenerate = Callable[[str], str | Mapping[str, Any] | Sequence[str]]

QUESTION_SYSTEM_PROMPT = """You are a business analyst helping turn a rough business problem into a student project task. Ask concise, source-relevant clarification questions. Focus on missing readiness information: business need, target users, available data and access, deliverable, measurable success, constraints, and business-team interaction. Never answer the questions or invent facts. Preserve the source language. Return JSON only."""


def generate_questions(
    initial_draft: str,
    llm_generate: LLMGenerate | None = None,
    *,
    minimum: int = 3,
    maximum: int = 7,
) -> list[str]:
    """Generate and validate 3-7 clarification questions for a draft."""
    draft = _clean_text(initial_draft)
    if not draft:
        raise ValueError("initial_draft is required and cannot be empty")
    if minimum < 3 or maximum < minimum or maximum > 10:
        raise ValueError("question limits must satisfy 3 <= minimum <= maximum <= 10")

    generator = llm_generate or openai_question_generate
    prompt = build_questions_prompt(draft, minimum=minimum, maximum=maximum)
    raw = generator(prompt)
    questions = _parse_questions(raw)
    if len(questions) < minimum:
        raise ValueError(f"question generator returned fewer than {minimum} questions")
    return questions[:maximum]


def generate_questions_offline(initial_draft: str) -> list[str]:
    """Provide a deterministic readiness questionnaire for local demos/tests."""
    draft = _clean_text(initial_draft)
    if not draft:
        raise ValueError("initial_draft is required and cannot be empty")
    return [
        "Who are the target users or beneficiaries of this solution?",
        "What data, examples, or other materials are available, and under what access conditions?",
        "What concrete deliverable should the student team produce?",
        "Which measurable targets and verification method will define success?",
        "What scope, deadline, privacy, legal, budget, or technical limitations apply?",
        "Which skills or technologies are required or preferred?",
        "Who is the business contact, and how often can they provide feedback?",
    ]


def build_questions_prompt(initial_draft: str, *, minimum: int = 3, maximum: int = 7) -> str:
    return f"""Read the rough task below and ask {minimum} to {maximum} high-value clarification questions.

Prioritize uncertainties that affect the deterministic readiness score. Avoid
asking for information already clearly stated. Each item must be one direct
question. Return exactly this JSON shape:
{{"questions": ["Question 1", "Question 2", "Question 3"]}}

Rough task:
{initial_draft}
"""


def openai_question_generate(prompt: str, *, model: str | None = None, timeout: int = 30) -> str:
    api_key = _get_openai_api_key()
    request_body = {
        "model": model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
        "store": False,
        "input": [
            {"role": "developer", "content": QUESTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 900,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenAI request failed with HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError("Could not reach the OpenAI API.") from error
    return _extract_openai_output_text(body)


def _parse_questions(value: str | Mapping[str, Any] | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("question generator returned invalid JSON") from error
    if isinstance(value, Mapping):
        value = value.get("questions", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("question generator must return a question list or JSON object")
    result = []
    for item in value:
        question = _clean_text(item)
        if question and question not in result:
            result.append(question)
    return result


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None
