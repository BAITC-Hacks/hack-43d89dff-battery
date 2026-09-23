# Engineering Handoff: Business Task-Card Marketplace

## Product idea

This repository is a five-hour hackathon MVP for the AI Sana case: gamification of practical business tasks.

A business representative writes a rough task description. The system asks clarification questions, turns the answers into an editable task card, calculates the task's readiness score, and publishes it in an open catalog. Student teams browse/filter tasks, submit proposals, and the business manually accepts or rejects proposals.

The central gamification target is the **business task's readiness**, not company prestige and not student rankings. A better-defined task receives a higher score and a better catalog position. The system must never automatically assign a team.

## Required end-to-end flow

1. Business enters a weak draft in any language (KZ/RU/EN mixed).
2. Question-generation model (`generateQuestions.py` - AI Task Architect) normalizes the draft, does a provisional 100-point evaluation to find gaps, and asks 3-5 targeted clarifying questions in a specified `TARGET_LANGUAGE`.
3. Business answers them.
4. Task-card model (`generateTaskCard.py`) converts draft, Q&A, and summary into an editable card matching the updated `TaskCard` dictionary schema.
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
├── frontend/                    # Vanilla HTML/CSS/JS SaaS UI
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── backend/
    ├── server.py                # Built-in http.server functioning as API router
    └── models/
        ├── generateQuestions.py # Implements the AI Task Architect & provisional Evaluation Engine
        ├── generateTaskCard.py  # Implements task-card generation with the new schema template
        └── evaluateTaskCard.py  # Reserved for final deterministic readiness scoring
```

The project now includes a simple frontend UI (SaaS aesthetic) and an HTTP server routing APIs, utilizing only standard-library Python to maintain the dependency-free MVP state.

## Persistence schema

`Database.initialize()` idempotently creates tables. Use `Database.read()` for
reads and `Database.transaction()` for writes. Transactions use `BEGIN
IMMEDIATE`, foreign keys, rollback on error, and connection close.

| Table | Important columns / guarantees |
| --- | --- |
| `businesses` | Business profile plus `owner_token_hash`. |
| `teams` | Team profile, `skills_json`, contact and `owner_token_hash`. |
| `tasks` | Raw draft, question/answer JSON, card/evaluation JSON, status/timestamps, FK business. |
| `proposals` | FK task/team, proposal text, links/status/timestamps; one team per task once. |

`tasks.status` is exactly `awaiting_answers`, `card_ready`, `confirmed`, or
`published`.

```text
create task       => awaiting_answers
submit answers    => card_ready
edit card         => card_ready, confirmation reset, score recalculated
confirm card      => confirmed, confirmation metadata false, score recalculated
publish task      => published, score recalculated
```

Published task cards cannot be regenerated or edited. Publishing a published
task is idempotent. Proposals start as `submitted`; only `accepted` and
`rejected` are currently user-driven. The schema permits `withdrawn` for a
future explicit withdraw action. SQLite permits exactly one accepted proposal
per task. Other proposals deliberately remain submitted after acceptance.

For schema changes, add a real backwards-compatible migration; `CREATE TABLE
IF NOT EXISTS` does not alter existing SQLite tables.

## Authorization and visibility

This is MVP authorization, not full production identity:

- Business/team creation returns a high-entropy `owner_token` exactly once.
- Only its SHA-256 hash is persisted.
- Protected calls use raw `X-Owner-Token`.
- A business token owns task creation, edits, confirmation, publication,
  proposal review, and proposal decision.
- A team token owns proposal submission and its own proposal list.
- Public viewers see only published tasks. They never receive drafts, answers,
  tokens, or owner-only metadata.

Do not return tokens from read/list endpoints or weaken the separate business
and team ownership checks.

## HTTP API

Bodies/responses are JSON. Error shape:

```json
{"error": {"code": "validation_error", "message": "..."}}
```

| Method | Endpoint | Body / behavior | Token |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness. | No |
| `GET` | `/api/meta/readiness` | Weights and levels. | No |
| `POST` | `/api/businesses` | `name` required; profile/contact optional. | No |
| `POST` | `/api/teams` | `name`, `contact_email` required; description/skills optional. | No |
| `POST` | `/api/tasks` | `business_id`, `initial_draft`; returns questions. | Business |
| `POST` | `/api/tasks/{id}/answers` | `answers` list of 3+; optional `task_summary`. | Business |
| `PATCH` | `/api/tasks/{id}/card` | Partial editable-card patch. | Business |
| `POST` | `/api/tasks/{id}/confirm` | Confirms current generated/edited card. | Business |
| `POST` | `/api/tasks/{id}/publish` | Requires confirmation. | Business |
| `GET` | `/api/tasks/{id}` | Owner-aware detail. | Optional business |
| `GET` | `/api/businesses/{id}/tasks` | Own task list. | Business |
| `GET` | `/api/catalog` | Published catalog. | No |
| `GET` | `/api/catalog/{id}` | Published task detail. | No |
| `POST` | `/api/tasks/{id}/proposals` | `team_id`, `message`, `approach`; optional timeline/links. | Team |
| `GET` | `/api/tasks/{id}/proposals` | Task proposals with team detail. | Business |
| `GET` | `/api/teams/{id}/proposals` | Own proposal list. | Team |
| `PATCH` | `/api/proposals/{id}/decision` | `{"decision":"accepted"}` or `rejected`. | Business |

Catalog filters: `tags` (CSV, all must match, case-insensitive), `industry`,
`readiness` (`draft|working|ready|priority`), `min_score` (0–100), `q`,
`limit` (1–100; default 50), and `offset` (0+). Results are score-descending,
then latest publication. Filtering currently happens in Python after published
rows are read, which is intentional for MVP scale.

Expected errors: `422` invalid input, `403` invalid ownership, `404` missing or
private resource, `409` invalid state/duplicate, `502` generation failure.

## Task-card contract

Every normalized card has these fields:

```text
title, context, business_need, target_users, required_skills, available_data,
limitations, expected_result, success_criteria, business_contact,
interaction_format, industry, tags, missing_information, warnings,
source_mapping, generation_metadata
```

Nested shapes:

```json
{
  "available_data": {"description": null, "sources": [], "access_conditions": null},
  "success_criteria": [{"metric": "...", "target": "...", "verification_method": "..."}],
  "business_contact": {"name": null, "role": null, "email": null},
  "interaction_format": {"channel": null, "frequency": null, "feedback_process": null},
  "generation_metadata": {"generated_by": "...", "requires_human_confirmation": true}
}
```

API-editable fields are only:

```text
title, context, business_need, target_users, required_skills, available_data,
limitations, expected_result, success_criteria, business_contact,
interaction_format, industry, tags
```

Protected fields are `missing_information`, `warnings`, `source_mapping`, and
`generation_metadata`. Nested patches to data/contact/interaction merge with
the current object; arrays replace their current array. Preserve this behavior
unless versioning the API.

## Model contracts and source-grounding

```python
generate_questions(initial_draft, llm_generate=None, minimum=3, maximum=7) -> list[str]
generate_questions_offline(initial_draft) -> list[str]
generate_task_card(payload, llm_generate=None) -> dict
generate_task_card_offline(payload) -> dict
evaluate_task_card(card) -> dict
readiness_level(score) -> str
```

Card-generation input requires a non-empty `initial_draft`, 3+ non-empty
questions, and 3+ non-empty answers. Answers may be ordered strings aligned to
questions or objects with `question` and `answer`.

Source requirements:

1. Answers override draft; draft overrides summary.
2. Never invent contacts, metrics, deadlines, data, access, skills, or tech.
3. Keep unknown facts null/empty and report gaps.
4. Tags may be normalized discovery terms only when source-grounded.
5. Generated output always needs human confirmation and cannot publish/assign.

Offline questions cover users, data/access, deliverable, success, limitations,
skills, and business interaction. Use custom/injected generators for provider
experiments rather than coupling providers to storage or scoring.

## Deterministic readiness scoring

`evaluate_task_card` must remain model-free and deterministic. It returns
`score`, `max_score`, `readiness_level`, criterion `breakdown`, missing fields,
improvement suggestions, and `scoring_version`.

| Area | Points | Rule |
| --- | ---: | --- |
| Context + business need | 20 | 10 points for each non-empty field. |
| Data/materials | 20 | Description 12, sources 4, access conditions 4. |
| Expected result | 15 | Concrete non-empty deliverable. |
| Success criteria | 15 | Metric 5, target 7, verification 3. |
| Limitations | 10 | Non-empty list. |
| Target users | 10 | Non-empty list. |
| Contact + interaction | 10 | Contact 3, role 2, channel 3, cadence/feedback 2. |

Levels are `draft` 0–39, `working` 40–69, `ready` 70–89, and `priority`
90–100. If scoring changes, increment `scoring_version`, update docs/tests,
and plan a refresh of persisted `evaluation_json` records.

## Change checklist and verification

When extending functionality:

1. Put workflow rules in `MarketplaceService`, not routes/models.
2. Preserve authorization and public/private response separation.
3. For a new card field, update template, normalization, prompts, editable
   allowlist (if appropriate), docs, tests, and evaluator if score-relevant.
4. For database changes, implement a migration and test an existing DB.
5. For a new proposal action, define valid source status and all transitions.
6. Test with no OpenAI key; tests must not consume credits or expose secrets.

Verified command:

```bash
python3 -B -m unittest discover -s tests -v
```

The suite covers score boundaries, full/empty cards, token enforcement,
confirmation-before-publishing, catalog filtering, proposal creation, and a
complete offline task-to-manual-acceptance workflow. Local socket binding was
restricted in the development sandbox, so add HTTP-level integration tests in
an environment where a test port can be opened.

## Intentional non-goals

Do not add full authentication/password recovery, real-time chat,
notifications, calendars, file storage, custom model training/vector DBs,
production deployment, mobile work, or a complete project tracker unless the
user explicitly reprioritizes the MVP.
