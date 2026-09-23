# Engineering Handoff: Business Task-Card Marketplace

## Product rules

This hackathon MVP turns rough business challenges into publishable student-team
tasks. The business must answer clarification questions, review and confirm an
editable task card, then explicitly decide whether to accept or reject a team
proposal.

Readiness is the gamification target. It is neither company prestige nor a
student ranking. Do not implement automatic team selection, assignment, or
rejection. Low-readiness tasks stay publishable and can receive proposals.

```text
draft -> questions -> answers -> editable card -> confirm -> publish
      -> public catalog -> team proposal -> manual business decision
```

## Implemented architecture

The code is dependency-free Python: `http.server` serves JSON and SQLite stores
state. No package install is needed.

```text
backend/
├── api.py                    # HTTP routes, JSON/CORS/error handling, executable server
├── database.py               # SQLite schema, reads, write transactions
├── service.py                # Validation, ownership, workflow, catalog, proposals
└── models/
    ├── generateQuestions.py  # OpenAI or deterministic questions
    ├── generateTaskCard.py   # Source-grounded OpenAI or offline task cards
    └── evaluateTaskCard.py   # Deterministic 0–100 readiness scoring
tests/
├── test_evaluate_task_card.py
└── test_marketplace_workflow.py
```

Run from repository root:

```bash
python3 -m backend.api
python3 -B -m unittest discover -s tests -v
```

Default server/database: `127.0.0.1:8000` and `data/marketplace.sqlite3`.

## Configuration and AI mode

| Variable | Default | Purpose |
| --- | --- | --- |
| `MARKETPLACE_HOST` | `127.0.0.1` | Server host. |
| `MARKETPLACE_PORT` | `8000` | Server port. |
| `MARKETPLACE_DB_PATH` | `data/marketplace.sqlite3` | SQLite database. |
| `MARKETPLACE_AI_MODE` | `auto` | `auto`, `online`, or `offline`. |
| `OPENAI_API_KEY` | unset | Enables live model calls. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Responses API model override. |
| `CORS_ORIGIN` | `*` | CORS response origin. |

`auto` uses OpenAI only when a key is available from environment or `.env`; it
otherwise uses deterministic offline generation. `offline` is ideal for local
demo/tests. `online` surfaces provider errors rather than inventing content.
OpenAI calls use `store: false`.

Never print, commit, or return API keys, authorization headers, or full
environment values. `.env`, SQLite files, and Python bytecode are ignored.

## Layering and extension boundaries

```text
MarketplaceHandler (api.py)
  -> MarketplaceService (service.py)
      -> generators / deterministic evaluator
      -> Database read or transaction context (database.py)
```

Keep `api.py` thin: parse HTTP/JSON and render errors there; put validation,
authorization, state transitions, and persistence orchestration in
`MarketplaceService`. Model modules must not write to SQLite or make workflow
decisions. `MarketplaceService` accepts injectable `question_generator` and
`card_generator` callables; preserve this provider/test seam.

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
