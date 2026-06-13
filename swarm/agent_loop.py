"""Agent runtime context + agent loop (spec sections 14, 15, 30).

Prototype 1 runs agents in-process and depth-first. Because a laptop realistically
serves one GPU model at a time (MAX_ACTIVE_GPU_AGENTS=1), the swarm executes
mostly sequentially: when a parent spawns children, each child runs to completion,
then the parent resumes with a summary of its children's results so it can
integrate and finish.
"""
from __future__ import annotations

from pathlib import Path

from . import ids, tools
from .context_builder import ContextBuilder
from .model_selector import ModelSelector
from .token_budget import ContextLimitReached, ensure_fits

AGENT_SUBDIRS = ["input", "output", "work", "terminal", "profiling", "optimization", ".trash", "logs"]


class RuntimeContext:
    def __init__(self, settings, db, events, selector: ModelSelector, client,
                 builder: ContextBuilder, executor=None):
        self.settings = settings
        self.db = db
        self.events = events
        self.selector = selector
        self.client = client
        self.builder = builder
        self.executor = executor
        self.swarm_id: str | None = None
        self.root_goal: str = ""

    # ----- agent creation -----
    def _make_agent_dir(self, agent_id: str) -> Path:
        base = self.settings.path("AGENT_WORKSPACE_DIR") / agent_id
        for sub in AGENT_SUBDIRS:
            (base / sub).mkdir(parents=True, exist_ok=True)
        return base / "work"

    def _new_agent_record(self, *, role: str, title: str, task: str, swarm_id: str,
                          parent_id: str | None, depth: int, explicit_model: str | None) -> dict:
        agent_id = ids.next_id("agent")
        work_dir = self._make_agent_dir(agent_id)
        cfg = self.selector.resolve(role, explicit_model=explicit_model)
        rec = {
            "id": agent_id,
            "swarm_id": swarm_id,
            "parent_agent_id": parent_id,
            "role": role,
            "title": title,
            "task": task,
            "status": "created",
            "depth": depth,
            "assigned_directory": str(work_dir),
            "primary_instruction_file": cfg.primary_instruction_file,
            "selected_model": cfg.selected_model,
            "model_source": cfg.model_source,
            "ollama_endpoint": cfg.endpoint,
            "execution_class": cfg.execution_class,
            "num_ctx": cfg.num_ctx,
            "num_predict": cfg.num_predict,
            "temperature": cfg.temperature,
            "completion_percentage": 0.0,
        }
        self.db.create_agent(rec)
        return rec

    def create_root(self, swarm_id: str, role: str, title: str, task: str) -> dict:
        self.swarm_id = swarm_id
        self.root_goal = task
        rec = self._new_agent_record(
            role=role, title=title, task=task, swarm_id=swarm_id,
            parent_id=None, depth=0, explicit_model=None,
        )
        self.db.set_swarm_root(swarm_id, rec["id"])
        return rec

    def create_child(self, *, parent, title: str, task: str, role: str,
                     done_condition: str, suggested_model: str | None, priority: int) -> dict:
        full_task = task
        if done_condition:
            full_task += f"\nDONE CONDITION: {done_condition}"
        return self._new_agent_record(
            role=role, title=title, task=full_task, swarm_id=parent["swarm_id"],
            parent_id=parent["id"], depth=int(parent["depth"]) + 1,
            explicit_model=suggested_model,
        )


class AgentRunner:
    def __init__(self, ctx: RuntimeContext, max_iterations: int = 12, max_parse_retries: int = 2):
        self.ctx = ctx
        self.max_iterations = max_iterations
        self.max_parse_retries = max_parse_retries

    def _parent_task(self, agent) -> str | None:
        pid = agent["parent_agent_id"]
        if not pid:
            return None
        parent = self.ctx.db.get_agent(pid)
        return parent["task"] if parent else None

    def _sibling_tasks(self, agent) -> list[str]:
        pid = agent["parent_agent_id"]
        if not pid:
            return []
        return [c["title"] for c in self.ctx.db.list_children(pid) if c["id"] != agent["id"]]

    def run_agent(self, agent_id: str) -> dict:
        db, ctx = self.ctx.db, self.ctx
        agent = db.get_agent(agent_id)
        agent_d = dict(agent)
        db.update_agent_status(agent_id, "started")
        ctx.events.agent_started(agent_d)

        parent_task = self._parent_task(agent)
        siblings = self._sibling_tasks(agent)
        history: list[dict] = []
        parse_retries = 0

        for _ in range(self.max_iterations):
            messages = ctx.builder.build_messages(
                agent_d, ctx.root_goal, parent_task, siblings, history
            )
            try:
                ensure_fits(
                    messages, int(agent["num_ctx"] or 8192),
                    int(agent["num_predict"] or 2048),
                    ctx.settings.get_int("TOKEN_SAFETY_MARGIN", 256) or 256,
                )
            except ContextLimitReached as e:
                result = {"status": "blocked", "failure": "context_limit_reached",
                          "note": str(e), "completion_percentage": 0}
                db.save_agent_result(agent_id, result)
                db.update_agent_status(agent_id, "blocked")
                ctx.events.agent_finished(agent_id, result)
                return result

            response = ctx.client.chat(
                endpoint=agent["ollama_endpoint"],
                model=agent["selected_model"],
                messages=messages,
                options={
                    "num_ctx": int(agent["num_ctx"] or 8192),
                    "num_predict": int(agent["num_predict"] or 2048),
                    "temperature": float(agent["temperature"] or 0.2),
                },
            )
            db.save_model_call(agent_id, response.telemetry)
            db.save_message(agent_id, "assistant", response.content)
            history.append({"role": "assistant", "content": response.content})

            calls = tools  # alias
            from .tool_parser import parse
            parsed = parse(response.content)

            if not parsed:
                parse_retries += 1
                if parse_retries > self.max_parse_retries:
                    result = {"status": "failed", "failure": "tool_parse_error",
                              "note": "agent never emitted a tool block", "completion_percentage": 0}
                    db.save_agent_result(agent_id, result)
                    db.update_agent_status(agent_id, "failed")
                    ctx.events.agent_finished(agent_id, result)
                    return result
                history.append({"role": "user", "content":
                    "You did not emit a tool block. You MUST respond with a "
                    "<<tool:tool_name>> ... <</tool>> block. To end, use <<tool:finish>>."})
                continue

            db.update_agent_status(agent_id, "running")
            resumed = False
            for call in parsed:
                if not call.ok:
                    history.append({"role": "user", "content":
                        f"Your <<tool:{call.name}>> block had invalid JSON ({call.error}). "
                        "Re-emit it as valid JSON."})
                    continue
                result, terminal = calls.execute(ctx, agent_id, call.name, call.args)
                db.save_tool_call(agent_id, call.name, call.args, result.get("status", "ok"), result)

                if call.name == "finish":
                    db.update_agent_status(agent_id, result["status"])
                    ctx.events.agent_finished(agent_id, result)
                    return result

                # Any tool that spawned children (spawn_agents, request_*) runs
                # them to completion, then the parent resumes with their results.
                if result.get("spawned"):
                    db.update_agent_status(agent_id, "waiting_for_children")
                    summaries = self._run_children(result.get("spawned", []))
                    history.append({"role": "user", "content":
                        "Your child agents finished. Results:\n" + summaries +
                        "\nIntegrate these results and finish with <<tool:finish>> "
                        "when your done condition is met."})
                    db.update_agent_status(agent_id, "running")
                    resumed = True
                    break  # rebuild messages with the new history

                # Feed the tool result back as a user-list entry; the agent iterates.
                history.append({"role": "user", "content":
                    f"Tool {call.name} result: {result}. Continue, or finish."})

            if resumed:
                continue

        # Ran out of iterations without finishing.
        result = {"status": "blocked", "failure": "max_iterations",
                  "note": "agent did not finish within iteration budget",
                  "completion_percentage": float(agent["completion_percentage"] or 0)}
        db.save_agent_result(agent_id, result)
        db.update_agent_status(agent_id, "blocked")
        ctx.events.agent_finished(agent_id, result)
        return result

    def _run_children(self, spawned: list[dict]) -> str:
        lines = []
        for child in spawned:
            res = self.run_agent(child["id"])
            lines.append(
                f"- {child['id']} ({child.get('role','?')}) [{res.get('status')}]: "
                f"{res.get('return_note') or res.get('note') or res.get('summary','')}"
            )
        return "\n".join(lines) if lines else "(no children completed)"
