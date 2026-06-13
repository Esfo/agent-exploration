#!/usr/bin/env python3
"""Bootstrap generator for static, user-editable scaffold files.

Creates the directory tree, settings/main.settings, all instruction files,
all prompt files, and the SQLite schema. These files are intended to be
user-editable after generation; this script only lays down the initial
versions. Re-running it will NOT overwrite files that already exist unless
--force is passed, so user edits are preserved.
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


def instruction(model: str, purpose: str, lines: list[str]) -> str:
    body = [f"MODEL: {model}", f"PURPOSE: {purpose}"]
    for i, ln in enumerate(lines, 1):
        body.append(f"{i:03d}. {ln}")
    return "\n".join(body) + "\n"


INSTRUCTIONS: dict[str, str] = {
    "global.txt": instruction(PH, "Instructions loaded by every agent.", [
        "Follow the assigned task exactly.",
        "Use the active instruction files in the order provided.",
        "Do not claim completion until the relevant checklist has been checked.",
        "Use tools only through explicit tool blocks.",
        "Do not invent tool results.",
        "Do not pretend a file exists if it has not been read or created.",
        "Return structured results when finished.",
        "If blocked, explain the exact blocker.",
        "Keep work scoped to the current task.",
        "Report meaningful progress when starting, waiting, completing, profiling, optimizing, or integrating.",
    ]),
    "chat_progenitor.txt": instruction(PH, "Controls the chat-facing progenitor model.", [
        "Speak directly to the user through the chat interface.",
        "Convert user requests into root swarm tasks when appropriate.",
        "Before starting a swarm, produce a to-do list.",
        "Include a model plan before starting the swarm.",
        "Start recursive swarms automatically when the task requires decomposition.",
        "Show runtime progress events in chat.",
        "Receive completion notes from child agents.",
        "Maintain the root swarm checklist.",
        "Report swarm completion percentage when agents start, progress, and finish.",
        "Report profiling and optimization findings when available.",
        "When the swarm completes, summarize result, files, commands, tests, models, profiling, optimization, and remaining issues.",
    ]),
    "planning.txt": instruction(PH, "Controls planning agents.", [
        "Restate the assigned goal in concrete terms.",
        "Create a checklist of required deliverables.",
        "Keep checklist items specific and independently verifiable.",
        "Mark which checklist items should become child agents.",
        "Mark which checklist items can be completed directly.",
        "Assign a done condition to every checklist item.",
        "Identify dependencies between checklist items.",
        "If code is involved, identify modules, tests, profiling, optimization, and integration needs.",
        "Return the checklist before spawning children.",
        "Do not create vague checklist items.",
    ]),
    "spawning.txt": instruction(PH, "Controls recursive swarm spawning.", [
        "If the assigned task has multiple separable deliverables, create a checklist.",
        "If a checklist item can be completed independently, spawn a child agent for it.",
        "Each spawned child must receive exactly one primary task.",
        "Each child task must include a done condition.",
        "Each child task must include relevant parent context.",
        "Each child task must include the expected output format.",
        "Do not spawn duplicate children for the same exact deliverable.",
        "If child outputs must work together, schedule a review or integration pass after workers finish.",
        "If profiling is needed, spawn profiling agents.",
        "If optimization is needed, spawn optimization agents after profiling.",
        "If system resources are constrained, allow the runtime to queue child agents.",
        "After spawning, report the child list and current swarm completion percentage.",
        "If the task benefits from deeper recursive decomposition, continue spawning children through the spawn_agents tool.",
    ]),
    "coding.txt": instruction(PH, "Controls code-writing agents.", [
        "Inspect relevant existing files before writing new code.",
        "Keep code scoped to the assigned task.",
        "Use the assigned directory for all direct coding work.",
        "Prefer small modules with clear interfaces.",
        "Use simple, testable code.",
        "Add tests when the task creates behavior.",
        "Use sandboxed terminal/Python tools for validation.",
        "If validation fails, attempt a fix.",
        "If validation still fails, report the exact failure.",
        "Document every file created or modified.",
        "If performance matters, request profiling.",
        "If profiling shows bottlenecks, request optimization.",
        "If integration with sibling outputs is needed, request an integration pass.",
        "Return only when the assigned coding task is complete or blocked.",
    ]),
    "terminal_execution.txt": instruction(PH, "Controls terminal use by agents.", [
        "Request terminals only through the terminal tool.",
        "Every terminal must be sandboxed.",
        "Every terminal must start in the assigned agent directory.",
        "Every command must include a reason.",
        "Every command must include the expected result.",
        "Every command must include a destructive-risk answer.",
        "Every command must be formatted exactly as required by the terminal command prompt file.",
        "Do not request a command that intentionally leaves the assigned directory.",
        "If a command needs another directory, request a new approved sandbox mount through the runtime.",
        "Inspect command output before deciding the next step.",
        "Include important terminal activity in the progress report.",
        "Include commands run in the finish note.",
    ]),
    "python_execution.txt": instruction(PH, "Controls Python execution.", [
        "Use Python execution for validation, inspection, profiling, transformations, and tests.",
        "Run Python only through the python tool or an approved sandboxed Python terminal.",
        "Do not assume Python code ran unless the runtime returns a result.",
        "Keep Python snippets task-specific.",
        "Use the assigned directory as the working directory.",
        "Do not request code that intentionally leaves the assigned directory.",
        "Always include a timeout.",
        "Inspect stdout, stderr, and exit code.",
        "Use profiling tools when performance analysis is requested.",
        "Include important Python results in the progress and finish notes.",
    ]),
    "shell_execution.txt": instruction(PH, "Controls shell execution.", [
        "Use shell commands only through the shell or sandboxed terminal tool.",
        "Prefer narrow commands over broad commands.",
        "Use the assigned directory as the working directory.",
        "Do not request shell commands that intentionally leave the assigned directory.",
        "Do not use sudo or host-system modification commands.",
        "Use shell commands for tests, linters, file listing, safe project commands, profiling, and diagnostics.",
        "Always include a timeout.",
        "Inspect stdout, stderr, and exit code.",
        "If a command fails, decide whether to fix, retry, profile, optimize, or report blocked.",
        "Include important shell results in the progress and finish notes.",
    ]),
    "command_questioning.txt": instruction(PH, "Ordered questions that every proposed command must answer before the runtime executes it.", [
        "What is the exact command?",
        "What directory will it run in?",
        "What is the reason for running it?",
        "What output or side effect is expected?",
        "Could this command delete files?",
        "Could this command overwrite files?",
        "Could this command modify files outside the assigned directory?",
        "Could this command access user-private data?",
        "Could this command modify the host operating system?",
        "Could this command install or remove packages?",
        "Could this command make network requests?",
        "Could this command consume excessive CPU, RAM, GPU, disk, or time?",
        "Is this destructive to the user ecosystem?",
        "Is there a narrower safer command?",
        "If the command is safe, provide the command block in the required format.",
        "If the command is risky, explain the risk and request a safer alternative.",
    ]),
    "curl_web.txt": instruction(PH, "Controls web fetching and documentation caching.", [
        "Use cached documentation before fetching a new page.",
        "Fetch only pages relevant to the current task.",
        "Prefer official documentation.",
        "Save fetched pages to the shared web cache.",
        "Record URL, fetch time, title, and reason.",
        "Summarize the cached page before using it in code decisions.",
        "Do not fetch private network URLs.",
        "Do not fetch unrelated pages.",
        "If a cached page is fresh enough, reuse it.",
        "Report cached pages used in progress and finish notes.",
    ]),
    "file_reading.txt": instruction(PH, "Controls file reading.", [
        "Read only files relevant to the assigned task.",
        "Use the read_file tool for file access.",
        "Do not assume file contents without reading them.",
        "Prefer reading narrow files over dumping large directories.",
        "Read from the assigned directory when working on local output.",
        "Read from project snapshots only when context is needed.",
        "Read from shared web cache only when documentation is relevant.",
        "Track files read if they influence the result.",
        "Include important files read in the progress and finish notes.",
        "If file reading is blocked, report the exact reason.",
    ]),
    "file_writing.txt": instruction(PH, "Controls file writing and saving.", [
        "Before writing a file, verify the target path is inside the assigned directory.",
        "Create parent directories only inside the assigned directory.",
        "Never overwrite a file without reading it first unless it is new.",
        "Save a file event for every write.",
        "Keep file writes task-specific.",
        "Do not write secrets, credentials, or machine-specific paths.",
        "After writing, read the file back if verification is needed.",
        "Do not write to the final project directory unless this agent is an approved integrator.",
        "Include written files in progress and finish notes.",
        "If writing fails, report the exact reason.",
    ]),
    "file_deleting.txt": instruction(PH, "Controls file deletion.", [
        "Delete only files inside the assigned directory unless integrator permissions allow otherwise.",
        "Prefer soft-delete by moving files to .trash.",
        "Never delete parent directories.",
        "Never delete project-level files unless this agent is an approved integrator.",
        "Record every delete event.",
        "Do not delete files just to hide errors.",
        "If replacing a file, prefer writing a corrected version rather than deleting first.",
        "Include deleted files in progress and finish notes.",
        "If deletion is blocked, report the exact reason.",
        "Do not attempt to bypass deletion restrictions.",
    ]),
    "finishing.txt": instruction(PH, "Controls how agents finish and report results upward.", [
        "Finish only through the finish tool.",
        "Do not finish until the assigned done condition is met or the task is blocked.",
        "Include a clear status: complete, blocked, or failed.",
        "Include a concise summary of what was accomplished.",
        "Include a return note to the parent agent.",
        "Include completion percentage.",
        "List files created, modified, and deleted.",
        "List commands run and sandboxes used.",
        "List remaining issues honestly.",
        "Do not claim success without verification.",
    ]),
    "review.txt": instruction(PH, "Controls reviewer agents.", [
        "Inspect the assigned output against the assigned task.",
        "Check whether the result is complete.",
        "Check whether the result is compatible with the parent project.",
        "Check for missing tests or validation.",
        "Check for obvious code errors.",
        "Check terminal outputs for unhandled errors.",
        "Check profiling/optimization claims if relevant.",
        "If the work is acceptable, mark review passed.",
        "If the work needs fixes, return specific fix tasks.",
        "If needed, spawn focused child reviewers.",
        "Include a clear pass/fail/block result.",
    ]),
    "integration.txt": instruction(PH, "Controls integration agents.", [
        "Inspect all relevant child outputs.",
        "Identify files created by each child.",
        "Identify overlapping or conflicting files.",
        "Identify incompatible interfaces.",
        "Merge compatible outputs into the project directory if permitted.",
        "Run project-level validation when possible.",
        "If integration fails, create specific fix tasks.",
        "Do not silently discard child work.",
        "Record every integrated file.",
        "Return integration status and remaining issues.",
        "If performance concerns appear, request profiling.",
        "If profiling finds bottlenecks, request optimization.",
    ]),
    "testing.txt": instruction(PH, "Controls tester agents.", [
        "Identify the smallest meaningful validation command.",
        "Run tests only through sandboxed terminal or sandboxed shell tools.",
        "Capture stdout, stderr, and exit code.",
        "If tests pass, report exactly what passed.",
        "If tests fail, summarize the failure precisely.",
        "If failures are fixable, request fix agents.",
        "Do not claim validation passed unless command output confirms it.",
        "Save test output logs.",
        "Include test command and result in finish note.",
        "If performance is relevant, request profiling.",
    ]),
    "fixing.txt": instruction(PH, "Controls fix agents.", [
        "Start from a specific failure report.",
        "Identify the smallest fix likely to resolve the failure.",
        "Modify only files relevant to the failure.",
        "Run the failing validation command again.",
        "If the fix works, report the before/after result.",
        "If the fix fails, report the remaining failure.",
        "Do not rewrite unrelated modules.",
        "If the failure indicates integration mismatch, request integration review.",
        "If performance regression appears, request profiling.",
        "Return fix status to parent.",
    ]),
    "profiling.txt": instruction(PH, "Controls profiling agents and profiling phases.", [
        "Profile only code relevant to the assigned task.",
        "Identify the exact command or workload being profiled.",
        "Record baseline runtime before optimization.",
        "Use cProfile for Python runtime profiling when appropriate.",
        "Use command timing for shell-level profiling.",
        "Capture memory-relevant observations when possible.",
        "Save profiling output to the agent profiling directory.",
        "Summarize the top bottlenecks.",
        "Do not optimize before identifying a bottleneck.",
        "Return profiling data to the parent.",
        "If optimization is warranted, request an optimization agent.",
    ]),
    "optimization.txt": instruction(PH, "Controls optimization agents.", [
        "Start from profiling results when available.",
        "Do not optimize code without a clear target.",
        "Preserve existing behavior.",
        "Make the smallest useful optimization first.",
        "Run validation after optimization.",
        "Compare before/after performance when possible.",
        "Record what changed and why.",
        "If optimization makes code less correct or less maintainable, revert or report blocked.",
        "Save optimization notes to the agent optimization directory.",
        "Return before/after summary to the parent.",
    ]),
    "progress_reporting.txt": instruction(PH, "Controls progress report behavior.", [
        "Report when starting a meaningful task.",
        "Report when spawning children.",
        "Report when beginning terminal work.",
        "Report when a command succeeds or fails if it changes the task state.",
        "Report when files are created, modified, or deleted.",
        "Report when web pages are cached.",
        "Report when profiling begins or ends.",
        "Report when optimization begins or ends.",
        "Report current completion percentage.",
        "Keep progress notes short and specific.",
        "Do not spam repeated progress messages for the same unchanged state.",
        "Finish with a completion note to the parent.",
    ]),
    "resource_pressure.txt": instruction(PH, "Controls behavior when CPU/RAM/GPU/disk resources are pressured.", [
        "If the runtime reports high resource pressure, prefer queueing new agents.",
        "If GPU is saturated, allow CPU routing for low-priority work.",
        "If RAM is saturated, pause low-priority agents.",
        "If disk is near limit, stop writing large files and report blocked.",
        "If active sandboxes are saturated, queue sandbox requests.",
        "If active terminals are saturated, queue terminal requests.",
        "If command queues are saturated, wait for running commands to finish.",
        "Do not fake progress while queued.",
        "Report that work is waiting on resources.",
        "Resume when the runtime allows it.",
    ]),
    "sandboxing.txt": instruction(PH, "Controls sandbox expectations for executable actions.", [
        "All terminal execution must be sandboxed.",
        "All shell execution must be sandboxed.",
        "All Python execution must be sandboxed.",
        "All test execution must be sandboxed.",
        "All profiling execution must be sandboxed.",
        "All optimization validation must be sandboxed.",
        "The sandbox must start in the assigned agent directory.",
        "The sandbox must not write outside approved writable mounts.",
        "If a command needs network access, request a web fetch or approved network sandbox.",
        "Include sandbox ID in progress and finish notes.",
    ]),
    "safety.txt": instruction(PH, "Loaded by all agents to constrain risky behavior.", [
        "Do not attempt to bypass runtime permissions.",
        "Do not request commands that intentionally leave the assigned directory.",
        "Do not access private network addresses.",
        "Do not use shell commands to modify the host system.",
        "Do not run commands without a timeout.",
        "Do not hide errors.",
        "Do not claim success without verification.",
        "If a safety rule blocks the task, return blocked with the reason.",
        "Prefer narrow, reversible actions.",
        "Answer command-questioning prompts before requesting command execution.",
    ]),
}


PROMPTS: dict[str, str] = {
    "agent_base.txt": (
        f"MODEL: {PH}\n"
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
        f"MODEL: {PH}\n"
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
        f"MODEL: {PH}\n"
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
        f"MODEL: {PH}\n"
        "PURPOSE: Defines context packet formatting.\n"
        "Include:\n"
        "    AGENT ID\n    ROLE\n    SELECTED MODEL\n    MODEL SOURCE\n    ROOT TASK\n"
        "    PARENT TASK\n    CURRENT TASK\n    ANCESTOR SUMMARY\n    SIBLING TASKS\n"
        "    ASSIGNED DIRECTORY\n    ACTIVE SANDBOX\n    ACTIVE TERMINAL\n    RELEVANT FILES\n"
        "    RELEVANT WEB CACHE\n    LOCAL CHECKLIST\n    ACTIVE INSTRUCTIONS\n    AVAILABLE TOOLS\n"
        "    RESOURCE STATE\n    COMPLETION RULE\n"
    ),
    "final_result.txt": (
        f"MODEL: {PH}\n"
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

# Recursion controls.
# Spec allows "unlimited"; during bring-up these conservative ceilings prevent
# runaway swarms from weak planner models. Set to "unlimited" to remove a ceiling.
MAX_RECURSION_DEPTH=3
MAX_TOTAL_AGENTS_PER_SWARM=20
MAX_CHILDREN_PER_AGENT=6
MAX_SPAWN_CALLS_PER_AGENT=3

# Resource behavior
MAX_ACTIVE_AGENTS_TOTAL=8
MAX_ACTIVE_GPU_AGENTS=1
MAX_ACTIVE_CPU_AGENTS=4
MAX_ACTIVE_SANDBOXES=8
MAX_ACTIVE_TERMINALS=8
MAX_ACTIVE_PYTHON_COMMANDS=4
MAX_ACTIVE_SHELL_COMMANDS=4
MAX_ACTIVE_WEB_FETCHES=2
MAX_RAM_PERCENT=80
MAX_CPU_PERCENT=85
MAX_VRAM_PERCENT=85
MAX_DISK_USAGE_PERCENT=90
RESOURCE_SAMPLE_INTERVAL_SECONDS=2
RESOURCE_PRESSURE_ACTION=queue_new_agents
COOLDOWN_SECONDS_AFTER_OOM=60

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

# Python execution
PYTHON_EXECUTION_ENABLED=true
PYTHON_DEFAULT_TIMEOUT_SECONDS=30
PYTHON_MAX_TIMEOUT_SECONDS=300
PYTHON_NETWORK_ENABLED=false
PYTHON_MAX_OUTPUT_KB=512

# Shell execution
SHELL_EXECUTION_ENABLED=true
SHELL_DEFAULT_TIMEOUT_SECONDS=30
SHELL_MAX_TIMEOUT_SECONDS=300
SHELL_NETWORK_ENABLED=false
SHELL_MAX_OUTPUT_KB=512

# Command questioning
COMMAND_QUESTIONING_ENABLED=true
COMMAND_QUESTION_FILE=instructions/command_questioning.txt
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
PROFILING_INSTRUCTION_FILE=instructions/profiling.txt
PROFILING_OUTPUT_DIR=workspace/profiling
PROFILE_PYTHON_WITH_CPROFILE=true
PROFILE_COMMAND_RUNTIME=true
PROFILE_MODEL_CALLS=true
PROFILE_TOOL_CALLS=true

# Optimization
OPTIMIZATION_ENABLED=true
OPTIMIZATION_INSTRUCTION_FILE=instructions/optimization.txt
OPTIMIZATION_OUTPUT_DIR=workspace/optimization
OPTIMIZATION_REQUIRES_PROFILING_FIRST=true
OPTIMIZATION_SHOULD_RUN_VALIDATION=true

# Instruction files
INSTRUCTION_GLOBAL=instructions/global.txt
INSTRUCTION_PROGENITOR=instructions/chat_progenitor.txt
INSTRUCTION_PLANNING=instructions/planning.txt
INSTRUCTION_SPAWNING=instructions/spawning.txt
INSTRUCTION_CODING=instructions/coding.txt
INSTRUCTION_TERMINAL=instructions/terminal_execution.txt
INSTRUCTION_PYTHON=instructions/python_execution.txt
INSTRUCTION_SHELL=instructions/shell_execution.txt
INSTRUCTION_COMMAND_QUESTIONING=instructions/command_questioning.txt
INSTRUCTION_CURL=instructions/curl_web.txt
INSTRUCTION_FILE_READING=instructions/file_reading.txt
INSTRUCTION_FILE_WRITING=instructions/file_writing.txt
INSTRUCTION_FILE_DELETING=instructions/file_deleting.txt
INSTRUCTION_FINISHING=instructions/finishing.txt
INSTRUCTION_REVIEW=instructions/review.txt
INSTRUCTION_INTEGRATION=instructions/integration.txt
INSTRUCTION_TESTING=instructions/testing.txt
INSTRUCTION_FIXING=instructions/fixing.txt
INSTRUCTION_PROFILING=instructions/profiling.txt
INSTRUCTION_OPTIMIZATION=instructions/optimization.txt
INSTRUCTION_PROGRESS=instructions/progress_reporting.txt
INSTRUCTION_RESOURCE_PRESSURE=instructions/resource_pressure.txt
INSTRUCTION_SANDBOXING=instructions/sandboxing.txt
INSTRUCTION_SAFETY=instructions/safety.txt

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
    for name, content in INSTRUCTIONS.items():
        results.append(write_file(ROOT / "instructions" / name, content, args.force))
    for name, content in PROMPTS.items():
        results.append(write_file(ROOT / "prompts" / name, content, args.force))
    results.append(write_file(ROOT / "swarm" / "schema.sql", SCHEMA_SQL, args.force))

    for line in results:
        print(line)
    print(f"\n{len(results)} static files processed.")


if __name__ == "__main__":
    main()
