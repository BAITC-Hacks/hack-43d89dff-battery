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
- Business and individual student accounts with email/password sign-in.
- Linked business/team profiles, private workspaces, and revocable sessions.
- SQLite persistence with automatic migration of existing marketplace data.
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

Choose **Sign in**, then **Create account**. Register as a business to post and
manage tasks, or as a student to submit proposals through your team profile.
Student credentials belong to an individual; the linked team profile supplies
the team's name and contact details. Each account currently has one profile;
joining existing teams and inviting additional members are future features.
Account roles are fixed at registration. Sign out to use a different account.

Passwords must contain 15–128 characters. Passwords are salted and hashed;
sessions use an HttpOnly cookie and are valid for seven days. Sign-out revokes
the current session. The browser keeps account information in memory and
restores it from the server after a reload. Auth credentials are never written
to local storage. Existing browser owner profiles can be linked during sign-up
using their saved ownership proof, preserving their tasks/proposals.

Task and proposal changes are saved only through the real API; a disconnected
server does not create local task data. Same-origin hosting is the supported
default. For HTTPS hosting, set `MARKETPLACE_COOKIE_SECURE=1`. Explicitly allowed
same-site frontend origins can use `CORS_ORIGIN` and
`window.MARKETPLACE_API_BASE`; wildcard credentialed CORS is not supported.
Email verification, password recovery, invitations, and production deployment
are not implemented.

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

Register or sign in first. Save the response's `profile.id` and `csrf_token`,
and retain the session cookie. Mutations require JSON, an allowed `Origin`,
and the session's `X-CSRF-Token`. Browsers send the cookie and Origin
automatically. The example values below are placeholders, not real credentials.

```bash
# 1. Register a business account and retain its cookie.
curl -sS -c /tmp/sana-cookies.txt http://127.0.0.1:8000/api/auth/register \
  -H 'Origin: http://127.0.0.1:8000' -H 'Content-Type: application/json' \
  -d '{"role":"business","name":"Aida","organization_name":"Acme","email":"aida@example.test","password":"REPLACE_WITH_YOUR_OWN_LONG_PASSWORD"}'

# 2. Start a task. Use profile.id and csrf_token from step 1.
curl -sS -X POST http://127.0.0.1:8000/api/tasks \
  -b /tmp/sana-cookies.txt -H 'Origin: http://127.0.0.1:8000' \
  -H 'Content-Type: application/json' -H 'X-CSRF-Token: CSRF_TOKEN' \
  -d '{"business_id":"biz_...","initial_draft":"We manually triage support requests and miss urgent cases."}'

# 3. Answer the generated questions, then inspect/edit card and score.
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../answers \
  -b /tmp/sana-cookies.txt -H 'Origin: http://127.0.0.1:8000' \
  -H 'Content-Type: application/json' -H 'X-CSRF-Token: CSRF_TOKEN' \
  -d '{"task_summary":"Build a ticket-prioritization prototype.","answers":["Support agents need faster triage","Anonymized tickets in a secure folder","A web prototype","80% accuracy verified against labelled tickets","No personal data; four weeks; Aida via weekly video calls"]}'

# 4. Confirm and publish. Low-scoring tasks are still eligible to publish.
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../confirm \
  -b /tmp/sana-cookies.txt -H 'Origin: http://127.0.0.1:8000' \
  -H 'Content-Type: application/json' -H 'X-CSRF-Token: CSRF_TOKEN' -d '{}'
curl -sS -X POST http://127.0.0.1:8000/api/tasks/task_.../publish \
  -b /tmp/sana-cookies.txt -H 'Origin: http://127.0.0.1:8000' \
  -H 'Content-Type: application/json' -H 'X-CSRF-Token: CSRF_TOKEN' -d '{}'

# 5. Browse the public catalog.
curl -sS 'http://127.0.0.1:8000/api/catalog?tags=support&readiness=ready'
```

## API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Create an individual account, linked profile, and session. |
| `POST` | `/api/auth/login` | Sign in with email and password. |
| `GET` | `/api/auth/session` | Restore current user/profile and CSRF token, or anonymous state. |
| `POST` | `/api/auth/logout` | Revoke the current session and clear its cookie. |
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

Protected endpoints require a valid session cookie and enforce the account's
role and profile ownership. `X-Owner-Token` is no longer accepted over HTTP;
old profile creation endpoints return 410. The catalog stays public. Responses
and errors are JSON: 401 for missing/expired authentication, 403 for forbidden
access or failed request protection, 409 for conflicts, 422 for invalid input,
and 429 for too many authentication attempts.

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

The tests cover scoring, the complete draft-to-proposal workflow, account and
session behavior, cross-account authorization, request protection, safe legacy
profile linking, and migration of a previous-schema SQLite database.
