"""Per-agent live conversation log, written into the agent's workspace.

Each agent gets workspace/agents/<id>/logs/conversation.md, appended in real
time as the conversation happens, so you can open/tail it to watch an agent
work. Content is fenced as code blocks so code displays monospaced.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Transcript:
    def __init__(self, agent: dict):
        self.path = Path(agent["assigned_directory"]).parent / "logs" / "conversation.md"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = (f"# {agent['id']} — {agent.get('role','?')}\n\n"
                  f"- **model:** {agent.get('selected_model','?')} "
                  f"({agent.get('execution_class','?')}, ctx={agent.get('num_ctx','?')})\n"
                  f"- **parent:** {agent.get('parent_agent_id') or 'user'}  "
                  f"**depth:** {agent.get('depth',0)}\n"
                  f"- **task:** {agent.get('task','')}\n\n---\n")
        try:
            self.path.write_text(header, encoding="utf-8")
        except OSError:
            pass

    def write(self, role: str, content: str) -> None:
        content = content if isinstance(content, str) else str(content)
        if "```" in content:
            body = content  # already fenced; leave as-is
        else:
            body = f"```\n{content}\n```"
        block = f"\n### {role} · {_ts()}\n\n{body}\n"
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(block)
        except OSError:
            pass
