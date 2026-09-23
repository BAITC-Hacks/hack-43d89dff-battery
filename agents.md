# Engineering Handoff: Business Task-Card Marketplace

## Product idea and working assumptions

This repository is a five-hour hackathon MVP for the AI Sana case: gamification of practical business tasks.

A business representative writes a rough task description. The system asks clarification questions, turns the answers into an editable task card, calculates the task's readiness score, and publishes it in an open catalog. Student teams browse/filter tasks, submit proposals, and the business manually accepts or rejects proposals.

The central gamification target is the **business task's readiness**, not company prestige and not student rankings. A better-defined task receives a higher score and a better catalog position. The system must never automatically assign a team.

This is a small, dependency-free hackathon MVP, not a production platform.
Keep changes focused on making this workflow clearer and more reliable. Do not
add a new framework, package manager, or external service unless the product
is explicitly reprioritized. Business/student authentication was explicitly
requested and is now part of the MVP. Read the code and its
tests before extending a behavior described here; the implementation and tests
are the source of truth if they differ from this document.

## Product end-to-end flow

1. Business enters a weak draft in any language (KZ/RU/EN mixed).
2. Question generation analyzes readiness gaps and returns 3–5 targeted
   questions. The online prompt asks the provider to preserve the source
   language. The offline generator currently returns five fixed English
   questions. Explicit `TARGET_LANGUAGE` selection is not implemented in the
   current UI/model signature.
3. Business answers them.
4. Task-card model (`generateTaskCard.py`) converts draft, Q&A, and summary into an editable card matching the updated `TaskCard` dictionary schema.
5. Rating engine scores confirmed fields from 0 to 100 and explains missing information.
6. Business confirms and publishes the task.
7. Students browse/filter the catalog and submit a proposal.
8. Business manually accepts or rejects proposals.

Keep the distinction between intended product behavior and implemented
behavior visible when proposing follow-up work; do not assume a language
selector, automatic company identity, or ranking of student teams already
exists.

## Current repository structure

```text
.
├── README.md
├── agents.md                    # This handoff document
├── .env                         # Local secret; ignored by Git
├── .gitignore                   # Must keep .env ignored
├── frontend/                    # Vanilla HTML/CSS/JS; no compile step
│   ├── index.html
│   ├── styles.css
│   ├── app.js                    # Shared UI helpers, hash router, catalog, public details
│   ├── api.js                    # Cookie API adapter and in-memory account/session state
│   ├── auth.js                   # Sign-up/sign-in, role gates, account and sign-out UI
│   ├── workspace.js              # Business workflow and team proposal workflow
│   ├── examples.js               # Fictional, read-only briefs for an empty/unavailable catalog
│   └── favicon.svg
├── backend/
│   ├── api.py                   # Canonical JSON API and allowlisted frontend asset server
│   ├── server.py                # Compatibility launcher that delegates to backend.api
│   ├── service.py               # Marketplace workflow, state rules, authorization
│   ├── auth.py                  # Accounts, password hashing, sessions, legacy profile linking
│   ├── database.py              # SQLite schema, reads, and transactions
│   └── models/
│       ├── generateQuestions.py # Question generation (provider and offline paths)
│       ├── generateTaskCard.py  # Task-card generation and normalization
│       └── evaluateTaskCard.py  # Final deterministic readiness scoring
└── tests/
    ├── test_marketplace_workflow.py
    ├── test_evaluate_task_card.py
    ├── test_model_boundaries.py
    ├── test_http_api.py
    ├── test_auth.py
    └── fixtures/legacy_schema.sql # Frozen pre-account schema for migration coverage
```

`python3 -m backend.api` is the canonical application entry point. It serves
the website and JSON API from one origin. `backend/server.py` exists only as a
compatible launcher; add routes and static assets to `backend/api.py`, not a
second router. The API serves only the explicit `FRONTEND_ASSETS` allowlist.
When adding a browser asset, add it to that allowlist and cover the route in
`tests/test_http_api.py`; never expose arbitrary repository paths, `.env`, or
database files through static serving.

## Frontend architecture and routes

The browser code is ordinary scripts loaded in this order from `index.html`:
`api.js`, `examples.js`, `auth.js`, `workspace.js`, then `app.js`. There is no bundler,
framework, CSS utility library, or component package. Keep this order when
adding globals; do not introduce module imports unless the page and server
serving rules are intentionally updated together.

- `index.html` owns the semantic page shell: header and navigation, account
  controls, main root (`#app-root`), footer, one shared native `<dialog>`, and
  a live-region toast.
- `app.js` owns the `#` hash router and catalog, public task details, the
  “how it works” and readiness pages, and the shared `window.UI` helpers
  (`escape`, `icon`, `modal`, `toast`, `navigate`, `taskCard`, `readiness`,
  and navigation refresh). Route names are `#catalog`, `#task/{id}`,
  `#how-it-works`, `#readiness`, `#create`, `#workspace`, `#edit/{id}`, and
  `#proposals`. When adding a route, update the router, page title, active
  navigation behavior, and mobile navigation behavior together.
- `workspace.js` exposes `window.Workspace.render(root, route, id)` for the
  business draft/questions/card/publish workflow and the two proposal views.
  `showProfile(role, afterSave)` delegates to account onboarding;
  `showProposal(task)` handles student submission. Keep workflow and
  form logic here rather than adding it to HTTP route code.
- `api.js` exposes `window.Api`. It translates browser actions to the REST API,
  includes the HttpOnly session cookie and `X-CSRF-Token` on mutations, and
  holds the user/profile/CSRF response in memory. `initSession()` restores it
  before initial routing. `getUser()` returns the individual account;
  `getProfile(role)` returns only the linked profile for the authenticated role.
  Account role `student` maps to the existing workflow role `team`.
  `register`, `login`, and `logout` update session state. New credentials must
  never be written to local storage. Old origin-keyed owner profiles are read
  only to offer explicit proof-based linking during registration.
- `auth.js` exposes `window.Auth`: `show`, `require(role, callback)`,
  `renderGate(root, role, resume)`, and `showAccount`. It owns account forms,
  validation, role conflicts, and account controls. A role selector changes
  registration intent only; it must never change the signed-in account's role.
  Preserve form input when onboarding interrupts a draft or proposal action.
- `examples.js` provides explicitly fictional, read-only catalog examples.
  Examples are marked `is_example`, are not returned by the server, and must
  never be submitted, published, or written into the SQLite database.
- `styles.css` contains the design tokens, base controls, layout components,
  pattern classes, and responsive breakpoints. Use the existing custom
  properties and classes before adding one-off values.

The current visual direction is Swiss International Typographic Style:
white, black, muted `#F2F2F2`, and signal red `#FF3000`; square corners; visible
rules; oversized, mostly uppercase Inter/Helvetica typography; and grid, dot,
or diagonal patterns. Red marks actions, section numbers, and status. Keep
content flush-left, use negative space deliberately, avoid gradients and
shadows, and make desktop and mobile states feel like the same system. Inter
loads from Google Fonts with a system sans-serif fallback; the page still
works without that network request.

Use semantic landmarks and headings, label controls, provide visible keyboard
focus, preserve keyboard operation and `prefers-reduced-motion`, and keep
touch targets usable. Escape user- or model-provided text before interpolating
it into HTML; prefer `textContent` for plain text, validate URLs before using
them as links, and encode IDs in browser routes/API paths. Never insert owner
tokens, drafts, or answers into public catalog/detail templates. The `#main-content`
skip link is handled specially so it focuses the main region without changing
the current route.

Catalog pagination currently retrieves API pages of up to 100 tasks and then
filters, sorts, and paginates the loaded list in the browser. If the catalog
outgrows MVP scale, move filtering/pagination server-side while preserving the
existing API query parameters and score-descending default. A live empty or
unavailable catalog can display labeled example briefs; actual task changes
must always use the API and surface connection failures to the user.

### Frontend API response shapes

The service returns canonical keys; frontend code should use these keys rather
than the old mock frontend's `*_json` names or `{task: ...}` wrappers:

```text
GET /api/catalog                 -> {items: Task[], total, limit, offset}
GET /api/tasks/{id}              -> Task
GET /api/businesses/{id}/tasks   -> Task[]
GET /api/tasks/{id}/proposals    -> Proposal[]
GET /api/teams/{id}/proposals    -> Proposal[]
POST/PATCH workflow actions      -> updated Task, Proposal, or profile

Task:     {id, business_id, business_name, status, card, evaluation,
           created_at, updated_at, published_at, ...owner-only fields}
Proposal: {id, task_id, team_id, message, approach, estimated_timeline,
           portfolio_links, status, created_at, ...team detail for business}
```

`GET /api/catalog` and `GET /api/catalog/{id}` are public. `GET /api/tasks/{id}`
is owner-aware: it returns owner-only draft, question, answer, and confirmation
fields only when called with the owning business session. Keep the UI aligned
with the service's response shape and session handling in `api.js`.

## Persistence schema

`Database.initialize()` idempotently creates base tables and applies versioned
migrations using `PRAGMA user_version` (current version 1). Use `Database.read()` for
reads and `Database.transaction()` for writes. Transactions use `BEGIN
IMMEDIATE`, foreign keys, rollback on error, and connection close.

| Table | Important columns / guarantees |
| --- | --- |
| `businesses` | Business profile plus `owner_token_hash`. |
| `teams` | Team profile, `skills_json`, contact and `owner_token_hash`. |
| `tasks` | Raw draft, question/answer JSON, card/evaluation JSON, status/timestamps, FK business. |
| `proposals` | FK task/team, proposal text, links/status/timestamps; one team per task once. |
| `accounts` | Individual name, unique normalized email, password hash, immutable business/student role, matching business/team FK. |
| `sessions` | SHA-256 token hash, account FK, creation and expiry timestamps. Raw cookies are never persisted. |

An individual student account is linked to one team profile for proposal
identity; business accounts link to one business profile. The current schema
allows one account per profile. Team membership, invitations, profile editing,
and changing an account's role are not implemented. Do not infer that a team
name grants another student membership or access to an existing team's data.

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

Accounts and sessions use only the standard library:

- Register with `role` (`business` or `student`), individual `name`, `email`,
  and `password`; business profiles use `organization_name`, student profiles
  use `team_name`. Each student signs in with individual credentials.
- Passwords are 15–128 characters, salted and hashed with PBKDF2-HMAC-SHA256
  (600,000 iterations). Preserve password whitespace and never log passwords.
- Sessions last seven days and use the `sana_session` cookie with HttpOnly,
  SameSite=Lax, Path=/. Set `MARKETPLACE_COOKIE_SECURE=1` when serving HTTPS.
  Only a SHA-256 hash is stored. Logout deletes the current server session.
- `GET /api/auth/session` returns `{user, profile, csrf_token, expires_at}`;
  anonymous values are null. `user` contains id/name/email/role. Register/login
  return this shape and set the cookie. Never return raw session tokens.
- Mutations require JSON and an allowed Origin. Session-authenticated mutations
  also require `X-CSRF-Token` derived from the current session token. Default
  access is same-origin; `CORS_ORIGIN` can allow one exact frontend origin.
  Never enable wildcard credentialed CORS or trust arbitrary forwarded hosts.
- `AuthService.authenticate` supplies an internal `AuthPrincipal` to the
  existing marketplace ownership arguments. Authorization is enforced in
  `MarketplaceService`, including both role and linked profile id.
- A business account owns task creation, edits, confirmation, publication,
  proposal review, and proposal decision.
- A student account owns proposal submission and its own team's proposal list.
- Public viewers see only published tasks. They never receive drafts, answers,
  tokens, or owner-only metadata.

`POST /api/businesses` and `/api/teams` are retired (410). `X-Owner-Token` does
not authorize HTTP requests. Legacy profile creation/raw-token support remains
in the Python service for compatibility and tests, limited to unclaimed
profiles. Registration can claim a legacy profile using both
`legacy_profile_id` and `legacy_owner_token`; the server verifies ownership,
links it atomically, and rotates its old token hash. Never claim by email or
name alone. Migration preserves old task/proposal ids and relationships.

Auth attempts are bounded by an in-process per-client rate limiter. This MVP
does not include email verification, password recovery, multi-worker shared
rate limiting, or team invitations. Do not imply these already exist.

## HTTP API

Bodies/responses are JSON. Error shape:

```json
{"error": {"code": "validation_error", "message": "..."}}
```

| Method | Endpoint | Body / behavior | Session role |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness. | No |
| `GET` | `/api/meta/readiness` | Weights and levels. | No |
| `POST` | `/api/auth/register` | Individual account + linked business/team profile. | No |
| `POST` | `/api/auth/login` | `email`, `password`; sets session cookie. | No |
| `GET` | `/api/auth/session` | Safe current account/profile and CSRF token, or anonymous. | Optional |
| `POST` | `/api/auth/logout` | Revokes session; clears cookie. | Optional; CSRF if authenticated |
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

Expected errors: `401` missing/expired authentication or invalid login, `422`
invalid input, `403` invalid ownership/Origin/CSRF, `404` missing or private
resource, `409` invalid state/duplicate email, `429` authentication rate limit,
`502` generation failure.

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
generate_questions(initial_draft, llm_generate=None, minimum=3, maximum=5) -> list[str]
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

### Model-output boundary safeguards

Treat all provider and injected-generator output as untrusted, even when a
provider is configured for JSON output:

- `generate_questions` accepts either a JSON object/list or fenced JSON,
  then strips empty/duplicate questions and requires the
  configured minimum.
- `generate_task_card` normalizes all schema fields. In particular,
  `missing_information` and `warnings` are always persisted as string lists;
  a provider returning `null`, a scalar, or malformed nested content must not
  crash the workflow.
- `MarketplaceService.submit_answers` normalizes a card again at the storage
  boundary before evaluation. This protects custom/injected card generators
  that return a partial card. It merges evaluator-detected gaps into
  `missing_information`.
- Custom question generators must return a list of 3–5 usable question
  strings. Custom card generators must return a mapping. Invalid injected
  output becomes a safe API error, never corrupted task JSON.

Preserve this defense-in-depth behavior when changing model providers or card
normalization. Do not trust the provider merely because its prompt requests an
exact JSON shape.

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

## How to extend the project safely

When implementing a user-facing feature, first trace the current route,
service method, stored representation, API response, browser adapter, and UI.
Put workflow rules and authorization in `MarketplaceService`; keep `api.py`
focused on HTTP parsing/serialization and keep prompts/scoring logic out of
routes. Make the smallest consistent change across those layers, then update
the README or this handoff when a contract changes.

For any task-card field change, consider every representation: generated-card
template and normalization, prompt, protected/editable allowlist, API patch
merge behavior, deterministic evaluator if score-relevant, frontend editor,
public task detail, example fixtures if useful, and tests/docs. Do not expose
protected generation metadata as editable input. Nested object patches merge;
array patches replace the array.

For schema changes, write an explicit backwards-compatible migration and
exercise it against a database created with the previous schema. `CREATE
TABLE IF NOT EXISTS` does not alter an existing table; a fresh database test
alone does not establish migration safety.

For proposal actions, define valid source statuses, allowed transitions,
ownership checks, response visibility, and collision behavior. SQLite has a
partial unique index allowing one accepted proposal per task. Preserve the
pre-check and map a competing acceptance's unique-index failure to the same
`409 task_already_has_team` result.

Model/provider output is untrusted even when JSON is requested. Preserve
normalization at both the model boundary and `MarketplaceService` storage
boundary. Add coverage for malformed, partial, duplicate, and fenced output
when changing that contract. Never require a real API key or consume model
credits for ordinary tests. Do not log or print secrets, owner tokens, or
private draft/answer contents in diagnostics.

For a browser feature, update `index.html` script order only if a new global
script is necessary. Use `window.Api` for real data and mutations, `window.UI`
for shared controls and rendering helpers, and `window.Workspace` for existing
business/team flows. Use `window.Auth` for account prompts. Preserve role-bound
sessions, never accept a client-selected role as authority, and keep public catalog
responses free of drafts, answers, tokens, and business-only metadata. If a
new static file is needed, add just that file to the API's explicit asset
allowlist. Do not restore local mock mutations; local example cards are
read-only.

New browser content must be escaped; external/user-supplied links must be
validated for `http:` or `https:` before being rendered as anchors. Keep
loading/error states, prevent duplicate form submission, handle navigation
during pending requests, and retain the user's input after an API error.
Preserve keyboard focus when replacing a form with its next step. Add the
appropriate narrow-screen CSS and verify it does not introduce horizontal
overflow.

## Verification

Run with Python 3.11 or newer (use the matching interpreter if `python3`
points to an older system Python). Verified project test command:

```bash
python3 -B -m unittest discover -s tests -v
```

The suite covers score boundaries, full/empty cards, session/role enforcement,
confirmation-before-publishing, catalog filtering, proposal creation, and a
complete offline task-to-manual-acceptance workflow. It also covers malformed
optional task-card fields, fenced question JSON, and persistence of a partial
injected task-card response. HTTP tests call the handler directly and cover API
behavior, the static asset allowlist, and private-file/traversal protection
without opening a local port. Account tests cover password hashing, normalized
email uniqueness, login/logout/expiry, cross-account isolation, proof-based
legacy business/team linking, and migration from the frozen version-zero
schema. Migration tests also assert failed upgrades roll back and future
schema versions are rejected without modifying their tables.

Frontend scripts need no package installation or build step. Optional syntax
checks use Node.js:

```bash
node --check frontend/api.js
node --check frontend/auth.js
node --check frontend/examples.js
node --check frontend/workspace.js
node --check frontend/app.js
```

Start the site from the repository root with `python3 -m backend.api`, then
open `http://127.0.0.1:8000/`. To force deterministic generation without model
calls, set `MARKETPLACE_AI_MODE=offline`. For manual browser testing, set
`MARKETPLACE_DB_PATH` and `MARKETPLACE_PORT` to isolate test data from the
default ignored `data/marketplace.sqlite3` database.

## Intentional non-goals

Do not add password recovery/email delivery, team invitations, real-time chat,
notifications, calendars, file storage, custom model training/vector DBs,
production deployment, mobile work, or a complete project tracker unless the
user explicitly reprioritizes the MVP.
