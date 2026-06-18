#!/usr/bin/env python3
"""Bootstrap generator for static, user-editable scaffold files.

Creates the directory tree, settings/main.settings, the prompt files, and the
SQLite schema. These are user-editable after generation; this script only lays
down the initial versions and will NOT overwrite existing files unless --force.

Instruction files are NOT generated here. They are authored, version-controlled
content (the PURPOSE/INPUT/VERIFY/FINISH grammar in docs/CHECKS.md); bootstrap
only validates that the files named in INSTRUCTION_NAMES are present.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Placeholder token: a MODEL line set to this means "fall back to settings".
PH = "<PLACEHOLDER_OLLAMA_MODEL>"

# Concrete default model baked into settings so the system runs with one pull.
DEFAULT_MODEL_TAG = "qwen2.5-coder:7b"

DIRS = [
    "settings",
    "instructions",
    "prompts",
    "runtime",
    "swarm",
    "swarm/tools",
    "swarm/runtime_guards",
    "swarm/sandbox",
    "workspace/project",
    "workspace/project_snapshot",
    "workspace/shared_readonly",
    "workspace/profiling",
    "workspace/optimization",
    "workspace/agents",
    "cache/web/pages",
    "logs",
    "tests",
]


# Instruction files are authored, version-controlled content (the VERIFY/FINISH
# grammar described in docs/CHECKS.md). Bootstrap no longer carries their bodies;
# it only knows their names so a fresh checkout can be validated. Edit the files
# in instructions/ directly — they are the source of truth.
INSTRUCTION_NAMES: list[str] = [
    "global", "safety", "progress_reporting", "command_questioning",
    "sandboxing", "resource_pressure",
    "chat_agent", "planning", "spawning", "coding_agent", "testing_agent",
    "testing", "review", "integration", "fixing", "profiling", "optimization",
    "summarizing", "philosophizing", "curl_web", "finishing", "zipper_agent",
    "file_reading", "file_writing", "file_deleting",
    "terminal_execution", "python_execution", "shell_execution",
    "convergence", "verify",
]


PROMPTS: dict[str, str] = {
    "agent_base.txt": (
        "PURPOSE: Base prompt loaded by all agents.\n"
        "You are an autonomous recursive local agent.\n"
        "You are assigned one task.\n"
        "You may complete it directly, use tools, or spawn child agents.\n"
        "You must work only through available tool blocks.\n"
        "You do not directly control the host machine.\n"
        "You request terminal, Python, shell, file, web, profiling, optimization, and spawn actions through tool blocks.\n"
        "All terminal/code execution is sandboxed by the runtime.\n"
        "You must follow the active instruction files in exact line order.\n"
        "You must report progress when meaningful.\n"
        "You must finish through the finish tool.\n"
    ),
    "tool_format.txt": (
        "PURPOSE: Defines tool syntax.\n"
        "Tool blocks must use this format:\n"
        "\n"
        "<<tool:tool_name>>\n"
        "{\n"
        '  "key": "value"\n'
        "}\n"
        "<</tool>>\n"
        "\n"
        "Do not describe tool usage without emitting a tool block.\n"
    ),
    "terminal_command_format.txt": (
        "PURPOSE: Defines exact terminal command formatting.\n"
        "Every terminal command request must use:\n"
        "\n"
        "<<tool:terminal_command>>\n"
        "{\n"
        '  "terminal_id": "agent_current",\n'
        '  "working_directory": "assigned",\n'
        '  "reason": "...",\n'
        '  "expected_result": "...",\n'
        '  "destructive_risk_answer": "...",\n'
        '  "timeout_seconds": 30,\n'
        '  "command": "..."\n'
        "}\n"
        "<</tool>>\n"
        "\n"
        "The runtime will reject commands that do not include reason, expected result, "
        "working directory, timeout, and destructive-risk answer.\n"
    ),
    "context_packet.txt": (
        "PURPOSE: Defines context packet formatting.\n"
        "Include:\n"
        "    AGENT ID\n    ROLE\n    SELECTED MODEL\n    MODEL SOURCE\n    ROOT TASK\n"
        "    PARENT TASK\n    CURRENT TASK\n    ANCESTOR SUMMARY\n    SIBLING TASKS\n"
        "    ASSIGNED DIRECTORY\n    ACTIVE SANDBOX\n    ACTIVE TERMINAL\n    RELEVANT FILES\n"
        "    RELEVANT WEB CACHE\n    LOCAL CHECKLIST\n    ACTIVE INSTRUCTIONS\n    AVAILABLE TOOLS\n"
        "    RESOURCE STATE\n    COMPLETION RULE\n"
    ),
    "final_result.txt": (
        "PURPOSE: Defines finish output.\n"
        "Finish only through the finish tool.\n"
        "Include:\n"
        "    status\n    summary\n    note\n    completion percentage\n    files created\n"
        "    files modified\n    files deleted\n    commands run\n    sandboxes used\n"
        "    web pages used\n    profiling results\n    optimization results\n"
        "    children spawned\n    remaining issues\n    return note to parent\n"
    ),
}


# num_ctx values default to "auto" so the model probe fills them from /api/show.
MAIN_SETTINGS = f"""# ==================================================
# MAIN SETTINGS CONTROL FILE
# ==================================================

RUNTIME_NAME=recursive_local_swarm
RUNTIME_VERSION=0.1

# Ollama endpoints
OLLAMA_GPU_ENDPOINT=http://localhost:11434
OLLAMA_CPU_ENDPOINT=http://localhost:11434

# Default model. Every role falls back to this unless overridden below or in an
# instruction file's MODEL: line, so you only need one model pulled to start.
DEFAULT_MODEL={DEFAULT_MODEL_TAG}
DEFAULT_PROGENITOR_MODEL={PH}
DEFAULT_PLANNER_MODEL={PH}
DEFAULT_SPAWNER_MODEL={PH}
DEFAULT_CODE_MODEL={PH}
DEFAULT_TERMINAL_MODEL={PH}
DEFAULT_PYTHON_MODEL={PH}
DEFAULT_SHELL_MODEL={PH}
DEFAULT_RESEARCH_MODEL={PH}
DEFAULT_FILE_MODEL={PH}
DEFAULT_REVIEW_MODEL={PH}
DEFAULT_INTEGRATION_MODEL={PH}
DEFAULT_TESTER_MODEL={PH}
DEFAULT_FIX_MODEL={PH}
DEFAULT_PROFILING_MODEL={PH}
DEFAULT_OPTIMIZATION_MODEL={PH}
DEFAULT_FINISH_MODEL={PH}

# Model override rules
ALLOW_INSTRUCTION_FILE_MODEL_OVERRIDE=true
ALLOW_PHASE_MODEL_SWITCHING=true
IF_INSTRUCTION_FILE_MODEL_MISSING=use_main_settings_default
IF_INSTRUCTION_FILE_MODEL_INVALID=fail_agent_start
IF_MODEL_NOT_INSTALLED=fail_agent_start

# Context sizes.
# "auto" => probe the model via /api/show and use its native context_length.
# A number => hard cap (the smaller of this and the model's native limit is used).
PROGENITOR_NUM_CTX=auto
PLANNER_NUM_CTX=auto
SPAWNER_NUM_CTX=auto
CODE_NUM_CTX=auto
TERMINAL_NUM_CTX=auto
PYTHON_NUM_CTX=auto
SHELL_NUM_CTX=auto
RESEARCH_NUM_CTX=auto
FILE_NUM_CTX=auto
REVIEW_NUM_CTX=auto
INTEGRATION_NUM_CTX=auto
TESTER_NUM_CTX=auto
FIX_NUM_CTX=auto
PROFILING_NUM_CTX=auto
OPTIMIZATION_NUM_CTX=auto
FINISH_NUM_CTX=auto

# Optional hard ceiling applied to any auto-detected context (0 = no ceiling).
# Useful on a laptop GPU where a model's native 128k context will not fit in VRAM.
MAX_AUTO_NUM_CTX=16384

# Output reservations
DEFAULT_NUM_PREDICT=2048
PROGENITOR_NUM_PREDICT=4096
PLANNER_NUM_PREDICT=4096
SPAWNER_NUM_PREDICT=2048
CODE_NUM_PREDICT=4096
TERMINAL_NUM_PREDICT=2048
PYTHON_NUM_PREDICT=2048
SHELL_NUM_PREDICT=2048
RESEARCH_NUM_PREDICT=2048
REVIEW_NUM_PREDICT=2048
INTEGRATION_NUM_PREDICT=4096
TESTER_NUM_PREDICT=2048
FIX_NUM_PREDICT=4096
PROFILING_NUM_PREDICT=2048
OPTIMIZATION_NUM_PREDICT=4096
FINISH_NUM_PREDICT=2048

# Token budgeting
TOKEN_SAFETY_MARGIN=256
SUMMARIZE_CONTEXT_WHEN_OVER_BUDGET=true
MAX_CONTEXT_SUMMARY_TOKENS=2048

# Spawn-inherit overflow: summarize the first SUMMARIZE_FRACTION of an
# over-large branch conversation via a summarizer agent before children inherit.
SUMMARIZE_ON_SPAWN_OVERFLOW=true
SUMMARIZE_FRACTION=0.6
SUMMARIZE_SPAWN_MAX_TOKENS=0
DEFAULT_SUMMARIZER_MODEL={PH}
SUMMARIZER_NUM_CTX=auto
SUMMARIZER_NUM_PREDICT=1024
SUMMARIZER_TEMPERATURE=0.2
INSTRUCTION_SUMMARIZING=instructions/summarizing

# Temperatures
PROGENITOR_TEMPERATURE=0.4
PLANNER_TEMPERATURE=0.3
SPAWNER_TEMPERATURE=0.25
CODE_TEMPERATURE=0.15
TERMINAL_TEMPERATURE=0.1
PYTHON_TEMPERATURE=0.1
SHELL_TEMPERATURE=0.1
RESEARCH_TEMPERATURE=0.2
FILE_TEMPERATURE=0.0
REVIEW_TEMPERATURE=0.1
INTEGRATION_TEMPERATURE=0.1
TESTER_TEMPERATURE=0.1
FIX_TEMPERATURE=0.15
PROFILING_TEMPERATURE=0.1
OPTIMIZATION_TEMPERATURE=0.15
FINISH_TEMPERATURE=0.0

# Recursive spawning behavior
RECURSIVE_SPAWNING_ENABLED=true
AGENTS_MAY_SPAWN_CHILDREN=true
CHILD_AGENTS_MAY_SPAWN_CHILDREN=true
USER_MANUAL_SUBTASK_ASSIGNMENT_REQUIRED=false

# Recursion controls. Agents go DEEPER, not retreat. No ceilings by default.
MAX_RECURSION_DEPTH=unlimited
MAX_TOTAL_AGENTS_PER_SWARM=unlimited
MAX_CHILDREN_PER_AGENT=unlimited
MAX_SPAWN_CALLS_PER_AGENT=unlimited

# Resource behavior. GPU/CPU concurrency is MEASURED at startup (calibration),
# not hand-set. Leave = auto; calibration overrides in-memory.
MAX_ACTIVE_AGENTS_TOTAL=auto
MAX_ACTIVE_GPU_AGENTS=auto
MAX_ACTIVE_CPU_AGENTS=auto
MAX_ACTIVE_SANDBOXES=auto
MAX_ACTIVE_TERMINALS=auto
MAX_ACTIVE_WEB_FETCHES=2
MAX_RAM_PERCENT=80
MAX_CPU_PERCENT=85
MAX_VRAM_PERCENT=85
MAX_DISK_USAGE_PERCENT=90
RESOURCE_SAMPLE_INTERVAL_SECONDS=2
RESOURCE_PRESSURE_ACTION=queue_new_agents
COOLDOWN_SECONDS_AFTER_OOM=60
CALIBRATION_VRAM_FRACTION=0.9
CALIBRATION_CPU_FRACTION=1.0

# Routing
ROUTE_PROGENITOR_TO_GPU=true
ROUTE_PLANNER_TO_GPU=true
ROUTE_SPAWNER_TO_GPU=true
ROUTE_CODE_TO_GPU=true
ROUTE_TERMINAL_TO_CPU=true
ROUTE_RESEARCH_TO_CPU=true
ROUTE_FILE_TASKS_TO_CPU=true
ROUTE_REVIEW_TO_CPU_IF_GPU_BUSY=true
ROUTE_INTEGRATION_TO_GPU=true
ROUTE_TESTER_TO_CPU=true
ROUTE_FIX_TO_GPU=true
ROUTE_PROFILING_TO_CPU=true
ROUTE_OPTIMIZATION_TO_GPU=true
ROUTE_FINISH_TO_CPU=true

# Directories
ROOT_DIR=.
SETTINGS_DIR=settings
INSTRUCTIONS_DIR=instructions
PROMPTS_DIR=prompts
RUNTIME_DIR=runtime
WORKSPACE_DIR=workspace
AGENT_WORKSPACE_DIR=workspace/agents
PROJECT_DIR=workspace/project
PROJECT_SNAPSHOT_DIR=workspace/project_snapshot
SHARED_READONLY_DIR=workspace/shared_readonly
WEB_CACHE_DIR=cache/web
LOG_DIR=logs
DATABASE_PATH=runtime/state.sqlite

# Sandboxing
SANDBOX_ALL_TERMINAL_EXECUTION=true
SANDBOX_ALL_PYTHON_EXECUTION=true
SANDBOX_ALL_SHELL_EXECUTION=true
SANDBOX_ALL_TEST_EXECUTION=true
SANDBOX_ALL_PROFILING_EXECUTION=true
SANDBOX_ALL_OPTIMIZATION_EXECUTION=true
SANDBOX_BACKEND=docker
SANDBOX_IMAGE=python:3.12-slim
SANDBOX_NETWORK_DEFAULT=none
SANDBOX_ALLOW_NETWORK_FOR_WEB_FETCH=false
SANDBOX_ALLOW_NETWORK_FOR_RESEARCH_TERMINALS=false
SANDBOX_MEMORY_MB=2048
SANDBOX_CPUS=2
SANDBOX_PIDS_LIMIT=256
SANDBOX_READ_ONLY_ROOT=true
SANDBOX_DROP_CAPABILITIES=true
SANDBOX_NO_NEW_PRIVILEGES=true

# Directory confinement inside sandbox
TERMINALS_START_IN_AGENT_DIRECTORY=true
TERMINALS_MUST_REMAIN_IN_AGENT_DIRECTORY=true
ENFORCE_CWD_BEFORE_EVERY_COMMAND=true
ENFORCE_CWD_AFTER_EVERY_COMMAND=true
RESET_CWD_AFTER_EVERY_COMMAND=true
ENFORCE_PATHS_IN_PYTHON_RUNTIME=true
ALLOW_AGENT_WRITE_OUTSIDE_ASSIGNED_DIR=false
ALLOW_WORKER_WRITE_PROJECT_DIR=false
ALLOW_INTEGRATOR_WRITE_PROJECT_DIR=true
SOFT_DELETE=true
MAX_FILE_WRITE_MB=5
MAX_AGENT_DIR_MB=200

# Python/shell timeouts come from the agent's tool call (guided by instructions),
# not from settings. Network is governed by the sandbox.

# Command questioning
COMMAND_QUESTIONING_ENABLED=true
COMMAND_QUESTION_FILE=instructions/command_questioning
BLOCK_COMMAND_IF_DESTRUCTIVE_SCORE_HIGH=true
REQUIRE_COMMAND_REASON=true
REQUIRE_COMMAND_EXPECTED_RESULT=true
REQUIRE_COMMAND_DIRECTORY=true
REQUIRE_COMMAND_DESTRUCTIVE_RISK_ANSWER=true

# Web
WEB_ACCESS_ENABLED=true
WEB_DEFAULT_TIMEOUT_SECONDS=20
WEB_MAX_DOWNLOAD_MB=10
WEB_DEFAULT_MAX_AGE_HOURS=168
WEB_BLOCK_PRIVATE_IPS=true
WEB_REUSE_CACHE_BY_DEFAULT=true
WEB_ALLOW_HTTP=false

# Progress reporting
PROGRESS_REPORTING_ENABLED=true
CHAT_SHOW_AGENT_START=true
CHAT_SHOW_AGENT_PROGRESS=true
CHAT_SHOW_AGENT_FINISH=true
CHAT_SHOW_SPAWN_EVENTS=true
CHAT_SHOW_COMPLETION_PERCENT=true
CHAT_SHOW_AGENT_NOTES=true
CHAT_SHOW_FILE_SUMMARIES=true
CHAT_SHOW_COMMAND_SUMMARIES=true
CHAT_SHOW_MODEL_USED=true
CHAT_SHOW_SANDBOX_USED=true
CHAT_SHOW_PROFILING_SUMMARIES=true
CHAT_SHOW_OPTIMIZATION_SUMMARIES=true

# Profiling
PROFILING_ENABLED=true
PROFILING_INSTRUCTION_FILE=instructions/profiling
PROFILING_OUTPUT_DIR=workspace/profiling
PROFILE_PYTHON_WITH_CPROFILE=true
PROFILE_COMMAND_RUNTIME=true
PROFILE_MODEL_CALLS=true
PROFILE_TOOL_CALLS=true

# Optimization
OPTIMIZATION_ENABLED=true
OPTIMIZATION_INSTRUCTION_FILE=instructions/optimization
OPTIMIZATION_OUTPUT_DIR=workspace/optimization
OPTIMIZATION_REQUIRES_PROFILING_FIRST=true
OPTIMIZATION_SHOULD_RUN_VALIDATION=true

# Instruction files
INSTRUCTION_GLOBAL=instructions/global
INSTRUCTION_PROGENITOR=instructions/chat_agent
INSTRUCTION_PLANNING=instructions/planning
INSTRUCTION_SPAWNING=instructions/spawning
INSTRUCTION_CODING=instructions/coding_agent
INSTRUCTION_TERMINAL=instructions/terminal_execution
INSTRUCTION_PYTHON=instructions/python_execution
INSTRUCTION_SHELL=instructions/shell_execution
INSTRUCTION_COMMAND_QUESTIONING=instructions/command_questioning
INSTRUCTION_CURL=instructions/curl_web
INSTRUCTION_FILE_READING=instructions/file_reading
INSTRUCTION_FILE_WRITING=instructions/file_writing
INSTRUCTION_FILE_DELETING=instructions/file_deleting
INSTRUCTION_FINISHING=instructions/finishing
INSTRUCTION_REVIEW=instructions/review
INSTRUCTION_INTEGRATION=instructions/integration
INSTRUCTION_TESTING=instructions/testing
INSTRUCTION_FIXING=instructions/fixing
INSTRUCTION_PROFILING=instructions/profiling
INSTRUCTION_OPTIMIZATION=instructions/optimization
INSTRUCTION_PROGRESS=instructions/progress_reporting
INSTRUCTION_RESOURCE_PRESSURE=instructions/resource_pressure
INSTRUCTION_SANDBOXING=instructions/sandboxing
INSTRUCTION_SAFETY=instructions/safety

# Prompt files
PROMPT_BASE=prompts/agent_base.txt
PROMPT_TOOL_FORMAT=prompts/tool_format.txt
PROMPT_CONTEXT_PACKET=prompts/context_packet.txt
PROMPT_TERMINAL_FORMAT=prompts/terminal_command_format.txt
PROMPT_FINAL_RESULT=prompts/final_result.txt
"""


SCHEMA_SQL = """-- SQLite state schema for recursive_local_swarm (spec section 28).
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
"""


def write_file(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return f"skip  {path.relative_to(ROOT)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"write {path.relative_to(ROOT)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    for d in DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
        gk = ROOT / d / ".gitkeep"
        if d.startswith(("workspace", "cache", "logs", "runtime")) and not any((ROOT / d).iterdir()):
            gk.write_text("", encoding="utf-8")

    results = [write_file(ROOT / "settings" / "main.settings", MAIN_SETTINGS, args.force)]
    for name, content in PROMPTS.items():
        results.append(write_file(ROOT / "prompts" / name, content, args.force))
    results.append(write_file(ROOT / "swarm" / "schema.sql", SCHEMA_SQL, args.force))

    # Instruction files are authored content tracked in git; bootstrap does not
    # generate them. Validate they are present and flag any that are missing.
    missing = [n for n in INSTRUCTION_NAMES if not (ROOT / "instructions" / n).exists()]
    for n in INSTRUCTION_NAMES:
        present = (ROOT / "instructions" / n).exists()
        results.append(f"{'ok   ' if present else 'MISS '} instructions/{n}")
    if missing:
        results.append(f"\nWARNING: {len(missing)} instruction file(s) missing: "
                       + ", ".join(missing) + "\nRestore them from version control.")

    for line in results:
        print(line)
    print(f"\n{len(results)} static files processed.")


if __name__ == "__main__":
    main()
