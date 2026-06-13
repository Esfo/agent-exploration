"""Context packet + prompt message assembly (spec sections 10, 13).

Builds the system prompt (base prompt + tool format + active instruction files)
and a user message containing the context packet and the current task. Agents
get a packet, not the full transcript.
"""
from __future__ import annotations

from .instructions import parse_instruction_file

# Instruction files every agent loads, plus role-specific ones.
GLOBAL_INSTRUCTION_KEYS = [
    "INSTRUCTION_GLOBAL",
    "INSTRUCTION_SAFETY",
    "INSTRUCTION_PROGRESS",
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
}

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
        keys = GLOBAL_INSTRUCTION_KEYS + ROLE_INSTRUCTION_KEYS.get(role, [])
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

    def context_packet(self, agent: dict, root_goal: str,
                       parent_task: str | None, sibling_tasks: list[str],
                       resource_state: str = "ok") -> str:
        lines = [
            "=== CONTEXT PACKET ===",
            f"AGENT ID: {agent['id']}",
            f"ROLE: {agent['role']}",
            f"SELECTED MODEL: {agent.get('selected_model','?')} ({agent.get('model_source','?')})",
            f"ROOT TASK: {root_goal}",
            f"PARENT TASK: {parent_task or '(none - you are root)'}",
            f"CURRENT TASK: {agent['task']}",
            f"SIBLING TASKS: {', '.join(sibling_tasks) if sibling_tasks else '(none)'}",
            f"ASSIGNED DIRECTORY: {agent.get('assigned_directory','?')}",
            f"DEPTH: {agent.get('depth',0)}",
            f"RESOURCE STATE: {resource_state}",
            "COMPLETION RULE: finish only when your done condition is met or you are blocked.",
            "=== END CONTEXT PACKET ===",
        ]
        return "\n".join(lines)

    def build_messages(self, agent: dict, root_goal: str, parent_task: str | None,
                       sibling_tasks: list[str], history: list[dict] | None = None,
                       memories_text: str = "") -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt(agent["role"])}]
        packet = self.context_packet(agent, root_goal, parent_task, sibling_tasks)
        if memories_text:
            packet += "\n\n" + memories_text
        messages.append({"role": "user", "content": packet + "\n\nBegin working on your CURRENT TASK now."})
        if history:
            messages.extend(history)
        return messages
