
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    contact_name TEXT,
    contact_email TEXT,
    owner_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    contact_email TEXT NOT NULL,
    owner_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(id),
    initial_draft TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '[]',
    task_summary TEXT,
    card_json TEXT,
    evaluation_json TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('awaiting_answers', 'card_ready', 'confirmed', 'published')
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    confirmed_at TEXT,
    published_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_business ON tasks(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, published_at DESC);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    team_id TEXT NOT NULL REFERENCES teams(id),
    message TEXT NOT NULL,
    approach TEXT NOT NULL,
    estimated_timeline TEXT,
    portfolio_links_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (
        status IN ('submitted', 'accepted', 'rejected', 'withdrawn')
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    decided_at TEXT,
    UNIQUE(task_id, team_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_accepted_proposal_per_task
ON proposals(task_id) WHERE status = 'accepted';
CREATE INDEX IF NOT EXISTS idx_proposals_task ON proposals(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_team ON proposals(team_id, created_at DESC);
