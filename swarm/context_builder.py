"""Context packet + prompt message assembly (spec sections 10, 13).

Builds the system prompt (base prompt + tool format + active instruction files)
and a user message containing the context packet and the current task. Agents
get a packet, not the full transcript.
"""
from __future__ import annotations

from .instructions import parse_instruction_file

# Instruction files every agent loads (and is gated by), plus role-specific and
# tool-derived ones. Each is a user-list of checks for its named process.
GLOBAL_INSTRUCTION_KEYS = [
    "INSTRUCTION_GLOBAL",
    "INSTRUCTION_SAFETY",
    "INSTRUCTION_PROGRESS",
    "INSTRUCTION_FINISHING",
]

ROLE_INSTRUCTION_KEYS = {
    "progenitor": ["INSTRUCTION_PROGENITOR", "INSTRUCTION_PLANNING", "INSTRUCTION_SPAWNING"],
    "planner": ["INSTRUCTION_PLANNING", "INSTRUCTION_SPAWNING"],
    "spawner": ["INSTRUCTION_SPAWNING"],
    "code": ["INSTRUCTION_CODING"],
    "reviewer": ["INSTRUCTION_REVIEW"],
    "integrator": ["INSTRUCTION_INTEGRATION"],
    "tester": ["INSTRUCTION_TESTING"],
    "fixer": ["INSTRUCTION_FIXING"],
    "profiler": ["INSTRUCTION_PROFILING"],
    "optimizer": ["INSTRUCTION_OPTIMIZATION"],
    "code_checker": ["INSTRUCTION_CODE_CHECKING"],
    "philosopher": ["INSTRUCTION_PHILOSOPHIZING"],
}

# Tool -> the process instruction file whose checks apply when the agent can use
# that tool. This is what makes python_execution.txt / file_writing.txt / etc.
# actually load and gate, instead of being dead files.
TOOL_INSTRUCTION_KEYS = {
    "write_file": "INSTRUCTION_FILE_WRITING",
    "append_file": "INSTRUCTION_FILE_WRITING",
    "read_file": "INSTRUCTION_FILE_READING",
    "list_files": "INSTRUCTION_FILE_READING",
    "delete_file": "INSTRUCTION_FILE_DELETING",
    "python": "INSTRUCTION_PYTHON",
    "shell": "INSTRUCTION_SHELL",
    "terminal_command": "INSTRUCTION_TERMINAL",
    "curl": "INSTRUCTION_CURL",
    "profile": "INSTRUCTION_PROFILING",
    "optimize": "INSTRUCTION_OPTIMIZATION",
    "spawn_agents": "INSTRUCTION_SPAWNING",
}


def instruction_keys_for(role: str) -> list[str]:
    """Ordered, de-duped instruction-file keys for an agent of this role:
    global + role-specific + one per tool the role can use."""
    keys = list(GLOBAL_INSTRUCTION_KEYS) + ROLE_INSTRUCTION_KEYS.get(role, [])
    for tool in tools_for_role(role):
        k = TOOL_INSTRUCTION_KEYS.get(tool)
        if k:
            keys.append(k)
    seen, ordered = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered

# Tools common to every agent.
COMMON_TOOLS = ["report_progress", "finish"]
# Spawning + worker tool sets.
SPAWN_TOOLS = ["spawn_agents"]
WORKER_TOOLS = ["list_files", "read_file", "write_file", "append_file",
                "delete_file", "python", "shell",
                "open_terminal", "terminal_command", "close_terminal"]
RECONCILE_TOOLS = ["request_review", "request_integration", "request_testing", "request_fix"]
WEB_TOOLS = ["curl", "search_web_cache", "read_cached_page"]
TERMINAL_TOOLS = ["open_terminal", "terminal_command", "close_terminal"]

# Which tool sets each role gets, beyond COMMON_TOOLS.
ROLE_TOOLSETS = {
    "progenitor": SPAWN_TOOLS + WORKER_TOOLS + RECONCILE_TOOLS,
    "planner": SPAWN_TOOLS,
    "spawner": SPAWN_TOOLS,
    "code": WORKER_TOOLS + ["request_review", "request_testing", "request_integration"] + WEB_TOOLS,
    "fixer": WORKER_TOOLS + ["request_testing"],
    "tester": WORKER_TOOLS + ["request_fix"],
    "reviewer": WORKER_TOOLS,
    "integrator": SPAWN_TOOLS + WORKER_TOOLS + ["request_testing", "request_review"],
    "optimizer": WORKER_TOOLS + ["optimize", "profile"],
    "profiler": WORKER_TOOLS + ["profile"],
    "researcher": WEB_TOOLS,
    # Stage-2 checker can read + run to verify; stage-3 philosopher is non-code.
    "code_checker": WORKER_TOOLS,
    "philosopher": ["read_file", "list_files"],
}

# Concise argument hints so small models emit the right JSON keys.
TOOL_HELP = {
    "spawn_agents": '{"children":[{"title":"..","task":"..","role":"code","done_condition":".."}]}',
    "report_progress": '{"message":"..","completion_percentage":50,"current_step":".."}',
    "finish": '{"status":"complete|blocked|failed","summary":"..","note":"..","files_created":[".."]}',
    "list_files": '{"path":"."}',
    "read_file": '{"path":"relative/file.py"}',
    "write_file": '{"path":"relative/file.py","content":"..full file contents.."}',
    "append_file": '{"path":"relative/file.py","content":".."}',
    "delete_file": '{"path":"relative/file.py","reason":".."}',
    "python": '{"reason":"..","expected_result":"..","destructive_risk_answer":"..","timeout_seconds":30,"code":".."}',
    "shell": '{"reason":"..","expected_result":"..","destructive_risk_answer":"..","timeout_seconds":30,"command":".."}',
    "request_review": '{"target":"what to review","context":".."}',
    "request_integration": '{"target":"outputs to integrate","context":".."}',
    "request_testing": '{"target":"what to test","context":".."}',
    "request_fix": '{"target":"the specific failure","context":".."}',
    "curl": '{"url":"https://..","purpose":"..","cache_policy":"reuse_if_fresh","max_age_hours":168}',
    "search_web_cache": '{"query":".."}',
    "read_cached_page": '{"cache_id":"..","max_chars":20000}',
    "open_terminal": '{"terminal_type":"shell","purpose":".."}',
    "terminal_command": '{"terminal_id":"terminal_0001","reason":"..","expected_result":"..","destructive_risk_answer":"..","timeout_seconds":30,"command":".."}',
    "close_terminal": '{"terminal_id":"terminal_0001"}',
    "profile": '{"target":"..","language":"python","reason":"..","expected_result":"..","destructive_risk_answer":"..","command":"python scan.py"}',
    "optimize": '{"target":"..","profiling_report_id":"..","goal":"..","validation_command":"python -m pytest","reason":"..","expected_result":"..","destructive_risk_answer":".."}',
}


def tools_for_role(role: str) -> list[str]:
    return COMMON_TOOLS + ROLE_TOOLSETS.get(role, [])


class ContextBuilder:
    def __init__(self, settings, available_tools=None):
        self.s = settings
        self.available_tools = available_tools

    def _render_instruction(self, key: str) -> str | None:
        rel = self.s.get(key)
        if not rel:
            return None
        path = self.s.root / rel
        if not path.exists():
            return None
        inst = parse_instruction_file(path)
        return f"# {path.name}\n{inst.render()}"

    def _render_prompt(self, key: str) -> str:
        rel = self.s.get(key)
        if not rel:
            return ""
        path = self.s.root / rel
        if not path.exists():
            return ""
        return parse_instruction_file(path).render()

    def system_prompt(self, role: str) -> str:
        parts = [self._render_prompt("PROMPT_BASE"), self._render_prompt("PROMPT_TOOL_FORMAT")]
        parts.append(
            "The numbered lines in the files below are CHECKS. Before you may finish "
            "\"complete\", the runtime verifies them one-by-one; if any check fails you "
            "are sent back to fix it. Work so that every check is true.")
        keys = instruction_keys_for(role)
        for key in keys:
            rendered = self._render_instruction(key)
            if rendered:
                parts.append(rendered)
        tools = self.available_tools or tools_for_role(role)
        tool_lines = "\n".join(f"  <<tool:{t}>>{TOOL_HELP.get(t, '{...}')}<</tool>>" for t in tools)
        parts.append(
            "AVAILABLE TOOLS (emit exactly one JSON object per block):\n" + tool_lines + "\n"
            "Write real files with write_file and run/verify them with python or shell — "
            "do NOT claim a file exists or a test passed unless a tool result confirms it. "
            "When the task is done (or blocked), you MUST emit a <<tool:finish>> block."
        )
        return "\n\n".join(p for p in parts if p)

    def build_messages(self, agent: dict, purpose_text: str,
                       inherited_history: list[dict] | None = None,
                       working_history: list[dict] | None = None,
                       memories_text: str = "") -> list[dict]:
        """Assemble the prompt for an agent.

        Layout: [system (role checks)] + the full INHERITED conversation of the
        branch this agent was spawned from + this agent's unique PURPOSE + this
        agent's own working turns. Children inherit the whole conversation; only
        the purpose is unique. The purpose is placed right before the agent's own
        work so it reads as 'here is the conversation… now, your job is…'.
        """
        messages = [{"role": "system", "content": self.system_prompt(agent["role"])}]
        if inherited_history:
            messages.extend(inherited_history)
        purpose = purpose_text
        if memories_text:
            purpose += "\n\n" + memories_text
        messages.append({"role": "user", "content": purpose})
        if working_history:
            messages.extend(working_history)
        return messages

