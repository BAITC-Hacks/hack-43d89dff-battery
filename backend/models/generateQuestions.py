"""Clarification-question generation for rough business task drafts."""

from __future__ import annotations

import json
import os
import re
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

DEFAULT_MINIMUM_QUESTIONS = 3
DEFAULT_MAXIMUM_QUESTIONS = 5

QUESTION_SYSTEM_PROMPT = """You are a business analyst optimizing the readiness score of a student project task.

Analyze the rough draft before choosing any questions. Ask only about facts that
are absent, unclear, or too vague to earn points under the supplied scoring
rubric. Select the smallest set of questions whose answers could recover the
largest number of missing points. Higher-value gaps come first. One concise
question may request closely related details from the same scoring area.

Do not use a fixed questionnaire. Do not ask for information already stated in
the draft. Do not prioritize unscored details while a scored gap remains. Never
answer a question or invent a fact. Preserve the draft's language, including a
mixed language when appropriate. Return JSON only."""


def generate_questions(
    initial_draft: str,
    llm_generate: LLMGenerate | None = None,
    *,
    minimum: int = DEFAULT_MINIMUM_QUESTIONS,
    maximum: int = DEFAULT_MAXIMUM_QUESTIONS,
) -> list[str]:
    """Use an LLM to select and validate 3-5 score-maximizing questions."""
    draft = _clean_text(initial_draft)
    if not draft:
        raise ValueError("initial_draft is required and cannot be empty")
    if minimum < 3 or maximum < minimum or maximum > 5:
        raise ValueError("question limits must satisfy 3 <= minimum <= maximum <= 5")

    generator = llm_generate or openai_question_generate
    prompt = build_questions_prompt(draft, minimum=minimum, maximum=maximum)
    raw = generator(prompt)
    questions = _parse_questions(raw)
    if len(questions) < minimum:
        raise ValueError(f"question generator returned fewer than {minimum} questions")
    return questions[:maximum]


def generate_questions_offline(initial_draft: str) -> list[str]:
    """Provide a deterministic five-question fallback for explicit offline use."""
    draft = _clean_text(initial_draft)
    if not draft:
        raise ValueError("initial_draft is required and cannot be empty")
    return [
        "What data, examples, or other materials are available, and under what access conditions?",
        "What concrete deliverable should the student team produce?",
        "Which measurable targets and verification method will define success?",
        "What current situation and business need should be improved, and who are the target users or beneficiaries?",
        "What limitations apply, and who is the business contact, through which channel, and how often can they provide feedback?",
    ]


def build_questions_prompt(
    initial_draft: str,
    *,
    minimum: int = DEFAULT_MINIMUM_QUESTIONS,
    maximum: int = DEFAULT_MAXIMUM_QUESTIONS,
) -> str:
    return f"""Analyze the rough task against this exact 100-point readiness rubric:

- Context: 10 points; business need: 10 points.
- Available data/materials: description 12 points, named sources 4 points,
  access/privacy/sharing conditions 4 points.
- Concrete expected deliverable: 15 points.
- Success criteria: measurable metric 5 points, concrete target 7 points,
  verification or acceptance method 3 points.
- Limitations: 10 points for confirmed scope, time, legal, privacy, budget, or
  technical constraints (an explicit confirmation that none apply is useful).
- Target users or beneficiaries: 10 points.
- Business contact and interaction: contact name or email 3 points, role 2
  points, communication channel 3 points, cadence or feedback process 2 points.

First determine which rubric details are already explicit enough to score. Then
choose {minimum} to {maximum} direct questions that maximize the potential point
gain from the missing details. Rank questions by expected score impact. Combine
closely related subfields when that makes one answer capable of earning all
points in an area. Do not ask about required skills, technologies, tags, title,
or industry unless every higher-value scored gap is already covered.

Return exactly this JSON shape and no analysis:
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
        value = value.strip()
        fenced = re.fullmatch(
            r"[\x60]{3}(?:json)?\s*(.*?)\s*[\x60]{3}",
            value,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            value = fenced.group(1)
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
