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

# Tools available in Prototype 1.
P1_TOOLS = ["spawn_agents", "report_progress", "finish"]


class ContextBuilder:
    def __init__(self, settings, available_tools=None):
        self.s = settings
        self.available_tools = available_tools or P1_TOOLS

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
        parts.append(
            "AVAILABLE TOOLS: " + ", ".join(self.available_tools) + "\n"
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
                       sibling_tasks: list[str], history: list[dict] | None = None) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt(agent["role"])}]
        messages.append({
            "role": "user",
            "content": self.context_packet(agent, root_goal, parent_task, sibling_tasks)
            + "\n\nBegin working on your CURRENT TASK now.",
        })
        if history:
            messages.extend(history)
        return messages
