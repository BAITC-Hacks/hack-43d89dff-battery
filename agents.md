# Project Handoff: Business Task-Card Marketplace

## Product idea

This repository is a five-hour hackathon MVP for the AI Sana case: gamification of practical business tasks.

A business representative writes a rough task description. The system asks clarification questions, turns the answers into an editable task card, calculates the task's readiness score, and publishes it in an open catalog. Student teams browse/filter tasks, submit proposals, and the business manually accepts or rejects proposals.

The central gamification target is the **business task's readiness**, not company prestige and not student rankings. A better-defined task receives a higher score and a better catalog position. The system must never automatically assign a team.

## Required end-to-end flow

1. Business enters a weak draft.
2. Question-generation model asks at least three relevant questions.
3. Business answers them.
4. Task-card model converts draft, Q&A, and summary into an editable card.
5. Rating engine scores confirmed fields from 0 to 100 and explains missing information.
6. Business confirms and publishes the task.
7. Students browse/filter the catalog and submit a proposal.
8. Business manually accepts or rejects proposals.

## Repository structure

```text
.
├── README.md
├── agents.md                    # This handoff document
├── .env                         # Local secret; ignored by Git
├── .gitignore                   # Must keep .env ignored
└── backend/
    └── models/
        ├── generateQuestions.py # Reserved for teammate's question-generation model
        ├── generateTaskCard.py # Implemented task-card generation model
        └── evaluateTaskCard.py # Reserved for deterministic readiness scoring
```

There is no HTTP server, database, frontend, dependency manifest, or package structure yet. The project currently uses only Python standard-library modules.

## Task-card requirements

The editable card needs these fields:

- title
- context
- business_need
- target_users
- required_skills
- available_data
- limitations
- expected_result
- success_criteria
- business_contact
- interaction_format
- industry
- tags
- missing_information
- warnings
- source_mapping
- generation_metadata

Rating-relevant fields and weights:

| Area | Points |
|---|---:|
| Context and business need | 20 |
| Data and materials | 20 |
| Expected result | 15 |
| Success criteria | 15 |
| Limitations | 10 |
| Target users | 10 |
| Business contact and interaction format | 10 |
| Total | 100 |

Readiness levels: 0-39 draft, 40-69 working, 70-89 ready, 90-100 priority. Low-scoring tasks remain visible and can receive proposals.

## Current implementation: generateTaskCard.py

### Main callable

```python
generate_task_card(payload, llm_generate=None) -> dict
```

Input contract:

```json
{
  "initial_draft": "Required free-text business description.",
  "clarifying_questions": [
    "At least three generated questions"
  ],
  "answers": [
    {
      "question": "Question text",
      "answer": "Business answer"
    }
  ],
  "task_summary": "Generated summary of the task"
}
```

Answers may alternatively be passed as ordered strings matching `clarifying_questions`.

Validation requires:

- non-empty `initial_draft`
- at least three non-empty questions
- at least three non-empty answers with associated questions

### LLM behavior

If no custom `llm_generate` callable is passed, `generate_task_card` uses `openai_llm_generate`.

- Provider: OpenAI Responses API
- Default model: `gpt-4o-mini`
- Override model with `OPENAI_MODEL`
- Key: `OPENAI_API_KEY` from environment or repository-root `.env`
- Persistence: API call includes `"store": false`
- Output mode: JSON object, followed by local normalization and validation
- No external Python package is required; the implementation uses `urllib.request`

The system prompt requires source-grounded extraction:

1. Question answers override the initial draft.
2. The initial draft overrides the generated summary.
3. The model must not invent contacts, metrics, deadlines, data, skills, or technologies.
4. Unknown facts are returned as `null` or `[]` and reported in `missing_information`.
5. Every output requires human confirmation before publication.
6. The model must create a title and context when source content is available.
7. Measurable statements become structured success criteria.
8. The LLM generates 3-8 concise tags for catalog filtering from the supported task domain, users, data, technologies, and implementation focus.

Tags are intentionally an exception to literal extraction: they are normalized discovery keywords derived from source material. They must still be grounded in the task; do not create unrelated tags.

### Output safeguards

- `_normalize_card` fills absent schema keys with safe defaults.
- `_parse_llm_response` accepts a JSON mapping/string and rejects invalid JSON.
- `_extract_openai_output_text` rejects incomplete or refused Responses API results.
- HTTP/network failures become safe `RuntimeError` messages and never include the API key.
- `missing_information` preserves LLM-reported gaps and adds rating-critical gaps.
- `source_mapping` ties populated fields to `initial_draft`, `task_summary`, or answer IDs such as `answer_3`.

A conservative `_deterministic_fallback` helper remains in the module but is not the current default path. It can be used only if an offline fallback is intentionally desired.

## Verified behavior so far

An end-to-end live OpenAI test was executed successfully with a customer-support triage scenario.

Input included:

- a rough draft about manually triaging support requests
- users: agents and support managers
- anonymized ticket data
- a web prototype as expected result
- measurable goals: 80% classification accuracy and 20% less triage time
- privacy/time limitations
- weekly consultation format

The LLM output successfully contained a title, context, target users, data description, limitations, expected result, two structured success criteria, interaction format, and `generated_by: "openai"`.

It correctly left business contact and industry missing when they were not supplied. The prompt was tightened after an earlier test initially omitted title, context, and success criteria. The tag-generation instructions were added afterward and were prompt-checked, but should receive one additional live test before the demo.

## How to run a manual task-card test

From the repository root:

```bash
python3 -B - <<'PY'
import json
from backend.models.generateTaskCard import generate_task_card

payload = {
    "initial_draft": "Our support team manually reviews customer requests and sometimes misses urgent issues.",
    "clarifying_questions": [
        "Who will use the solution?",
        "What data is available?",
        "How will success be measured?"
    ],
    "answers": [
        "Customer-support agents and support managers.",
        "Anonymized support tickets from the last 12 months.",
        "Reduce manual triage time by 20 percent."
    ],
    "task_summary": "Build an AI-assisted support-ticket prioritization prototype."
}

print(json.dumps(generate_task_card(payload), ensure_ascii=False, indent=2))
PY
```

This makes a real API call and can consume credits. Do not print, commit, or send the API key.

For offline tests, inject a fake generator:

```python
generate_task_card(payload, llm_generate=lambda _: '{"title": "Test task"}')
```

A fake response must still be valid JSON. The normalizer will fill missing card fields.

## Security rules

- `.env` is ignored by Git and must remain ignored.
- Never place `OPENAI_API_KEY` in Python code, README files, tests, chat messages, screenshots, or commits.
- Never log the Authorization header, API key, or complete environment.
- If the key is exposed, revoke and replace it immediately.
- Keep `.env.example` keyless if one is added.

## Next priorities

1. Implement `evaluateTaskCard.py` as deterministic scoring logic. Do not use an LLM for rating.
2. Define score breakdown and improvement suggestions for every rating criterion.
3. Implement/align `generateQuestions.py` with the input contract above.
4. Run a live tag-generation test and ensure tags are concise and filter-friendly.
5. Add automated unit tests for validation, API-response parsing, prompt behavior, and scoring.
6. Create an API layer and persistence for drafts, cards, teams, and proposals.
7. Build catalog filtering by tags/topic/readiness level.
8. Add team proposals and manual business accept/reject actions.
9. Add a README with setup, architecture, rating formula, and demo script.

## Non-goals for the hackathon

Do not spend time on:

- full authentication or password recovery
- real-time chat, notifications, calendar, or file storage
- training a custom ML model or vector database
- automatic team selection
- production deployment or mobile optimization
- a full project-management tracker

## Integration boundary

The eventual backend flow should be:

```text
draft + Q&A + summary
        -> generate_task_card
        -> human edits/confirms fields
        -> evaluate_task_card (deterministic 0-100)
        -> publish to catalog
        -> student proposal
        -> manual business decision
```

Keep LLM generation and deterministic rating separate. The LLM structures source information; the rating module decides readiness based only on confirmed fields.

