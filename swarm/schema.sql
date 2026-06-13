-- SQLite state schema for recursive_local_swarm (spec section 28).
CREATE TABLE IF NOT EXISTS swarms (
    id TEXT PRIMARY KEY,
    root_agent_id TEXT,
    user_goal TEXT NOT NULL,
    status TEXT NOT NULL,
    completion_percentage REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    swarm_id TEXT NOT NULL,
    parent_agent_id TEXT,
    role TEXT NOT NULL,
    title TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    depth INTEGER NOT NULL,
    assigned_directory TEXT NOT NULL,
    primary_instruction_file TEXT,
    selected_model TEXT,
    model_source TEXT,
    ollama_endpoint TEXT,
    execution_class TEXT,
    num_ctx INTEGER,
    num_predict INTEGER,
    temperature REAL,
    completion_percentage REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1,
    assigned_child_agent_id TEXT
);

CREATE TABLE IF NOT EXISTS sandboxes (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    backend TEXT NOT NULL,
    status TEXT NOT NULL,
    network_mode TEXT NOT NULL,
    memory_mb INTEGER,
    cpus REAL,
    mounts_json TEXT,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS terminals (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    sandbox_id TEXT NOT NULL,
    terminal_type TEXT NOT NULL,
    assigned_root TEXT NOT NULL,
    current_cwd TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS terminal_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal_id TEXT NOT NULL,
    sandbox_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    command TEXT NOT NULL,
    reason TEXT,
    expected_result TEXT,
    destructive_risk_answer TEXT,
    cwd_before TEXT,
    cwd_after TEXT,
    cwd_guard_passed INTEGER,
    exit_code INTEGER,
    stdout_path TEXT,
    stderr_path TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS file_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_cache (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status_code INTEGER,
    content_type TEXT,
    raw_path TEXT,
    extracted_path TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS progress_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    swarm_id TEXT,
    agent_id TEXT,
    message TEXT NOT NULL,
    completion_percentage REAL,
    current_step TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiling_reports (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    target TEXT NOT NULL,
    baseline_runtime_ms INTEGER,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS optimization_reports (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    target TEXT NOT NULL,
    before_runtime_ms INTEGER,
    after_runtime_ms INTEGER,
    improvement TEXT,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_results (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    note TEXT,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    num_ctx INTEGER,
    num_predict INTEGER,
    temperature REAL,
    prompt_eval_count INTEGER,
    eval_count INTEGER,
    duration_ms INTEGER,
    done_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    tags TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agents_swarm ON agents(swarm_id);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_progress_swarm ON progress_reports(swarm_id);
