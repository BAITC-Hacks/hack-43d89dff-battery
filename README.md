# Business Task-Card Marketplace

Dependency-free Python MVP backend for matching practical business challenges
with student teams. It gamifies task readiness—not company prestige or student
rankings—and never assigns a team automatically.

## What is implemented

- Draft intake and 3–5 score-maximizing clarification questions.
- Editable task-card generation from the draft and answers.
- Deterministic 0–100 readiness score with per-criterion explanations.
- Required business confirmation before publishing.
- Public catalog filtering by tag, industry, readiness, score, and text.
- Team proposals and an explicit business accept/reject decision.
- SQLite persistence and lightweight owner tokens for the MVP (not full auth).
- Responsive Swiss-style frontend with searchable task catalog, readiness and
  industry filters, business task editor, and student proposal workspace.

The server uses only the Python standard library. Question selection uses the
OpenAI Responses integration by default and reports a configuration error when
no `OPENAI_API_KEY` is available; this avoids silently substituting a fixed
questionnaire for draft analysis. Set `MARKETPLACE_AI_MODE=offline` explicitly
to use deterministic demo generation without network access.

## Run

Requires Python 3.11+ (tested with Python 3.14).

```bash
python3 -m backend.api
```

Open `http://127.0.0.1:8000` to use the website. The same server serves the
frontend and API and stores data in `data/marketplace.sqlite3` by default.
`python3 backend/server.py` and `python3 -m backend.server` are equivalent
launchers. Configuration is optional:

```bash
MARKETPLACE_PORT=8080 MARKETPLACE_AI_MODE=offline python3 -m backend.api
```

`/health` returns the server status. The database and its SQLite journal files
are ignored by Git. Keep `OPENAI_API_KEY` only in the ignored `.env` file or
environment; the API never returns it.

The frontend keeps separate business and team owner profiles in browser local
storage for this API origin. Switching roles keeps both profiles. Task and
proposal changes are saved only through the real API; a disconnected server
does not create local task data. If hosting the frontend separately, set
`window.MARKETPLACE_API_BASE` to the API server origin before loading `api.js`.

When the live catalog is empty or unavailable, the catalog displays clearly
labeled fictional example briefs. They are read-only and never persisted.
All actual task creation, publication, and proposal decisions use the API.
The frontend needs no package installation or build step. Inter is loaded
from Google Fonts, with Helvetica and Arial fallbacks when unavailable.

## Workflow

```text
business + draft
  -> clarification questions
  -> answers + generated editable card
  -> business edits and confirms
  -> deterministic readiness evaluation
  -> published catalog task
  -> team proposal
  -> manual business accept/reject
```

Create a business or team first. Each creation response includes a one-time
`owner_token`; save it and send it in `X-Owner-Token` for protected operations.

```bash
# 1. Create business; save id and owner_token from the response.
curl -sS -X POST http://127.0.0.1:8000/api/businesses \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme","contact_name":"Aida","contact_email":"aida@example.test"}'

# 2. Start a task. Returns clarification_questions.
curl -sS -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' -H 'X-Owner-Token: BUSINESS_TOKEN' \
  -d '{"business_id":"biz_...","initial_draft":"We manually triage support requests and miss urgent cases."}'

# 3. Answer the generated questions, then inspect/edit card and score.
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../answers \
  -H 'Content-Type: application/json' -H 'X-Owner-Token: BUSINESS_TOKEN' \
  -d '{"task_summary":"Build a ticket-prioritization prototype.","answers":["Support agents","Anonymized tickets in a secure folder","A web prototype","80% accuracy verified against labelled tickets","No personal data; four weeks","Python and UX","Aida via weekly video calls"]}'

# 4. Confirm and publish. Low-scoring tasks are still eligible to publish.
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../confirm \
  -H 'X-Owner-Token: BUSINESS_TOKEN'
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../publish \
  -H 'X-Owner-Token: BUSINESS_TOKEN'

# 5. Browse the public catalog.
curl -sS 'http://127.0.0.1:8000/api/catalog?tags=support&readiness=ready'
```

## API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/businesses` | Create a business and return its owner token. |
| `POST` | `/api/teams` | Create a student team and return its owner token. |
| `POST` | `/api/tasks` | Start a draft and get questions. |
| `POST` | `/api/tasks/{id}/answers` | Generate a task card from answers. |
| `PATCH` | `/api/tasks/{id}/card` | Edit card content; moves it back to `card_ready`. |
| `POST` | `/api/tasks/{id}/confirm` | Confirm the current card and score it. |
| `POST` | `/api/tasks/{id}/publish` | Publish a confirmed card. |
| `GET` | `/api/catalog` | Browse published tasks. |
| `GET` | `/api/catalog/{id}` | Read one published task. |
| `POST` | `/api/tasks/{id}/proposals` | Submit a team proposal. |
| `GET` | `/api/tasks/{id}/proposals` | Business reads proposals for its task. |
| `PATCH` | `/api/proposals/{id}/decision` | Business explicitly accepts or rejects a proposal. |

Protected endpoints use `X-Owner-Token`. The catalog is public. All responses
and errors are JSON; validation errors use HTTP 422.

## Readiness formula

| Area | Points |
| --- | ---: |
| Context and business need | 20 |
| Data and materials | 20 |
| Expected result | 15 |
| Success criteria | 15 |
| Limitations | 10 |
| Target users | 10 |
| Business contact and interaction | 10 |
| **Total** | **100** |

Levels: `draft` 0–39, `working` 40–69, `ready` 70–89, and `priority` 90–100.
The evaluator returns missing fields and improvement suggestions for every
unscored criterion.

## Test

```bash
python3 -B -m unittest discover -s tests -v
```

The tests cover scoring boundaries, a complete card, owner-token enforcement,
and the full draft-to-proposal workflow in a temporary SQLite database.
