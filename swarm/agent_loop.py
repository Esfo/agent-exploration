"""Agent runtime context + agent loop (spec sections 14, 15, 30).

Prototype 1 runs agents in-process and depth-first. Because a laptop realistically
serves one GPU model at a time (MAX_ACTIVE_GPU_AGENTS=1), the swarm executes
mostly sequentially: when a parent spawns children, each child runs to completion,
then the parent resumes with a summary of its children's results so it can
integrate and finish.
"""
from __future__ import annotations

from pathlib import Path

import threading

from . import ids, tools
from .context_builder import ContextBuilder
from .model_selector import ModelSelector
from .instructions import parse_instruction_file
from .transcript import Transcript
from .token_budget import (ContextLimitReached, _summarize_dropped, ensure_fits,
                           estimate_messages, safe_input_budget, summarize_to_fit)

AGENT_SUBDIRS = ["input", "output", "work", "terminal", "profiling", "optimization", ".trash", "logs"]


class RuntimeContext:
    def __init__(self, settings, db, events, selector: ModelSelector, client,
                 builder: ContextBuilder, executor=None, web_cache=None, scheduler=None):
        self.settings = settings
        self.db = db
        self.events = events
        self.selector = selector
        self.client = client
        self.builder = builder
        self.executor = executor
        self.web_cache = web_cache
        self.scheduler = scheduler
        self.memory = None
        self.branch = None
        self.control = None
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

    def _purpose_text(self, agent) -> str:
        """The agent's unique purpose, layered on top of the inherited conversation."""
        pid = agent["parent_agent_id"]
        adir = agent.get("assigned_directory", "?")
        if not pid:
            return (f"This is your purpose: ROLE: {agent['role']}. You are the root agent. "
                    "Handle the following request and return a complete result to the user:\n\n"
                    f"\"{agent['task']}\"\n\n"
                    "Decide for yourself whether to answer directly or to spawn a swarm. "
                    f"Work in {adir}. Follow your instruction checks below to drive your steps.")
        sibs = self.ctx.db.list_children(pid)
        idx = next((i + 1 for i, c in enumerate(sibs) if c["id"] == agent["id"]), None)
        num = f"#{idx} " if idx else ""
        return (f"This is your purpose: ROLE: {agent['role']}. You are an individual agent "
                f"({agent['id']}) working on {num}within the context of the conversation above. "
                "Your specific task:\n\n"
                f"\"{agent['task']}\"\n\n"
                f"It is your job to complete this and return your result to your parent branch "
                f"({pid}). Work only in {adir}. Now follow your instruction checks below to "
                "drive your next steps.")

    def run_agent(self, agent_id: str, inherited_history: list[dict] | None = None) -> dict:
        db, ctx = self.ctx.db, self.ctx
        agent = db.get_agent(agent_id)
        agent_d = dict(agent)
        db.update_agent_status(agent_id, "started")
        ctx.events.agent_started(agent_d)

        inherited = list(inherited_history or [])   # full conversation of the branch
        purpose_text = self._purpose_text(agent_d)  # this agent's unique purpose
        history: list[dict] = []                    # this agent's own working turns
        tx = Transcript(agent_d)                    # live conversation log in workspace
        tx.write("purpose", purpose_text)

        def feedback(text: str) -> None:            # append user msg + log it live
            history.append({"role": "user", "content": text})
            tx.write("runtime→agent", text)

        parse_retries = 0
        last_response = ""
        attempted: list[str] = []

        memories_text = ""
        if ctx.memory is not None:
            mems = ctx.memory.relevant(role=agent["role"], swarm_id=agent["swarm_id"],
                                       task=agent["task"])
            memories_text = ctx.memory.render(mems)

        for _ in range(self.max_iterations):
            # Cooperative pause/cancel checkpoint (live control commands).
            if ctx.control is not None:
                ctx.control.wait_if_paused(agent_id)
                if ctx.control.is_cancelled(agent_id):
                    result = {"status": "cancelled", "failure": "cancelled_by_user",
                              "note": "cancelled by user",
                              "completion_percentage": float(agent["completion_percentage"] or 0)}
                    db.save_agent_result(agent_id, result)
                    db.update_agent_status(agent_id, "cancelled")
                    ctx.events.agent_finished(agent_id, result)
                    return result

            messages = ctx.builder.build_messages(
                agent_d, purpose_text, inherited, history, memories_text
            )
            num_ctx_i = int(agent["num_ctx"] or 8192)
            num_predict_i = int(agent["num_predict"] or 2048)
            margin = ctx.settings.get_int("TOKEN_SAFETY_MARGIN", 256) or 256
            try:
                if ctx.settings.get_bool("SUMMARIZE_CONTEXT_WHEN_OVER_BUDGET", True):
                    messages = summarize_to_fit(
                        messages, num_ctx_i, num_predict_i, margin,
                        ctx.settings.get_int("MAX_CONTEXT_SUMMARY_TOKENS", 2048) or 2048)
                ensure_fits(messages, num_ctx_i, num_predict_i, margin)
            except ContextLimitReached as e:
                result = {"status": "blocked", "failure": "context_limit_reached",
                          "note": str(e), "completion_percentage": 0}
                db.save_agent_result(agent_id, result)
                db.update_agent_status(agent_id, "blocked")
                ctx.events.agent_finished(agent_id, result)
                return result

            options = {
                "num_ctx": int(agent["num_ctx"] or 8192),
                "num_predict": int(agent["num_predict"] or 2048),
                "temperature": float(agent["temperature"] or 0.2),
            }
            if ctx.scheduler is not None:
                with ctx.scheduler.inference_slot(agent["execution_class"], agent_id):
                    response = ctx.client.chat(
                        endpoint=agent["ollama_endpoint"], model=agent["selected_model"],
                        messages=messages, options=options)
            else:
                response = ctx.client.chat(
                    endpoint=agent["ollama_endpoint"], model=agent["selected_model"],
                    messages=messages, options=options)
            db.save_model_call(agent_id, response.telemetry)
            db.save_message(agent_id, "assistant", response.content)
            history.append({"role": "assistant", "content": response.content})
            tx.write("model", response.content)
            last_response = response.content

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
                feedback("You did not emit a tool block. You MUST respond with a "
                    "<<tool:tool_name>> ... <</tool>> block. To end, use <<tool:finish>>.")
                continue

            db.update_agent_status(agent_id, "running")
            resumed = False
            for call in parsed:
                if not call.ok:
                    feedback(f"Your <<tool:{call.name}>> block had invalid JSON ({call.error}). "
                        "Re-emit it as valid JSON.")
                    continue
                attempted.append(call.name)
                result, terminal = calls.execute(ctx, agent_id, call.name, call.args)
                db.save_tool_call(agent_id, call.name, call.args, result.get("status", "ok"), result)

                if result.get("failure") == "unknown_tool":
                    avail = ", ".join(ctx.builder.available_tools or
                                      __import__("swarm.context_builder", fromlist=["tools_for_role"])
                                      .tools_for_role(agent["role"]))
                    feedback(f"There is no tool named '{call.name}'. Use one of these EXACT names: "
                        f"{avail}. Re-emit a correct <<tool:NAME>> block.")
                    continue

                if call.name == "finish":
                    db.update_agent_status(agent_id, result["status"])
                    ctx.events.agent_finished(agent_id, result)
                    return result

                # Any tool that spawned children (spawn_agents, request_*) runs
                # them to completion, then the parent resumes with their results.
                if result.get("spawned"):
                    if ctx.control is not None and ctx.control.should_stop_waves():
                        feedback("Stop requested: do not start new sub-agents. Finish with "
                            "<<tool:finish>> using what you have so far.")
                        continue
                    db.update_agent_status(agent_id, "waiting_for_children")
                    # Children inherit this branch's FULL conversation so far.
                    branch_conversation = (inherited
                                           + [{"role": "user", "content": purpose_text}]
                                           + history)
                    if self._needs_summary(agent_d, branch_conversation):
                        branch_conversation = self._summarize_branch(agent_d, branch_conversation)
                    summaries = self._run_children(result.get("spawned", []), branch_conversation)
                    feedback("Your child agents finished. Results:\n" + summaries +
                        "\nIntegrate these results and finish with <<tool:finish>> "
                        "when your done condition is met.")
                    db.update_agent_status(agent_id, "running")
                    resumed = True
                    break  # rebuild messages with the new history

                # Feed the tool result back as a user-list entry; the agent iterates.
                feedback(f"Tool {call.name} result: {result}. Continue, or finish.")

            if resumed:
                continue

        # Ran out of iterations without finishing. Surface what the model did so
        # the failure is diagnosable instead of opaque.
        tools_seen = ", ".join(attempted) or "(none parsed)"
        snippet = " ".join(last_response.split())[:400] or "(empty response)"
        result = {"status": "blocked", "failure": "max_iterations",
                  "note": (f"Did not finish within {self.max_iterations} steps. "
                           f"Tools it tried: {tools_seen}. "
                           f"Last model output: {snippet}"),
                  "completion_percentage": float(agent["completion_percentage"] or 0)}
        db.save_agent_result(agent_id, result)
        db.update_agent_status(agent_id, "blocked")
        ctx.events.agent_finished(agent_id, result)
        return result

    # ----- spawn-inherit overflow: summarize the first fraction via an agent -----
    def _needs_summary(self, agent, conversation: list[dict]) -> bool:
        s = self.ctx.settings
        if not s.get_bool("SUMMARIZE_ON_SPAWN_OVERFLOW", True):
            return False
        cap = s.get_int("SUMMARIZE_SPAWN_MAX_TOKENS", 0) or 0
        if cap <= 0:  # derive from the parent's context budget
            cap = safe_input_budget(int(agent["num_ctx"] or 8192),
                                    int(agent["num_predict"] or 2048),
                                    s.get_int("TOKEN_SAFETY_MARGIN", 256) or 256)
        return estimate_messages(conversation) > max(1, cap)

    def _summarize_branch(self, parent, conversation: list[dict]) -> list[dict]:
        frac = self.ctx.settings.get_float("SUMMARIZE_FRACTION", 0.6) or 0.6
        k = max(1, int(len(conversation) * frac))
        to_sum, keep = conversation[:k], conversation[k:]
        summary = self._run_summarizer(parent, to_sum)
        prefix = {"role": "user",
                  "content": "[SUMMARY OF EARLIER CONVERSATION]\n" + summary}
        return [prefix] + keep

    def _run_summarizer(self, parent, to_sum: list[dict]) -> str:
        """Spawn a summarizer agent (its own role + instruction file) to compress
        the earlier conversation. Falls back to a deterministic recap if the model
        is unavailable, so a spawn never fails on summarization."""
        ctx = self.ctx
        max_summary = ctx.settings.get_int("MAX_CONTEXT_SUMMARY_TOKENS", 2048) or 2048
        child = ctx.create_child(
            parent=parent, title="Summarize earlier branch context",
            task="Summarize the earlier part of this branch conversation into a compact "
                 "briefing so a newly spawned agent can inherit the essential context.",
            role="summarizer", done_condition="", suggested_model=None, priority=1)
        ctx.events.agent_started(dict(child))

        rel = ctx.settings.get("INSTRUCTION_SUMMARIZING")
        sys_txt = "Summarize the conversation into a compact briefing."
        if rel and (ctx.settings.root / rel).exists():
            sys_txt = parse_instruction_file(ctx.settings.root / rel).render() or sys_txt
        conv_text = "\n\n".join(f"[{m.get('role','?')}] {m.get('content','')}" for m in to_sum)
        nctx, npred = int(child["num_ctx"] or 8192), int(child["num_predict"] or 1024)
        margin = ctx.settings.get_int("TOKEN_SAFETY_MARGIN", 256) or 256
        msgs = [{"role": "system", "content": sys_txt},
                {"role": "user", "content":
                 "Summarize the earlier conversation below into a compact briefing.\n\n" + conv_text}]
        try:
            msgs = summarize_to_fit(msgs, nctx, npred, margin, max_summary)
        except ContextLimitReached:
            pass

        summary = ""
        try:
            opts = {"num_ctx": nctx, "num_predict": npred,
                    "temperature": float(child["temperature"] or 0.2)}
            if ctx.scheduler is not None:
                with ctx.scheduler.inference_slot(child["execution_class"], child["id"]):
                    resp = ctx.client.chat(endpoint=child["ollama_endpoint"],
                                           model=child["selected_model"], messages=msgs, options=opts)
            else:
                resp = ctx.client.chat(endpoint=child["ollama_endpoint"],
                                       model=child["selected_model"], messages=msgs, options=opts)
            summary = (resp.content or "").strip()
            ctx.db.save_model_call(child["id"], resp.telemetry)
        except Exception:  # noqa: BLE001 - fall back, never break the spawn
            summary = ""
        if not summary:
            summary = _summarize_dropped(to_sum, max_summary)

        result = {"status": "complete", "summary": "summarized earlier context",
                  "note": summary[:500], "completion_percentage": 100}
        ctx.db.save_agent_result(child["id"], result)
        ctx.db.update_agent_completion(child["id"], 100)
        ctx.db.update_agent_status(child["id"], "complete")
        ctx.events.agent_finished(child["id"], result)
        return summary

    def _agent_conversation(self, agent_row, inherited: list[dict]) -> list[dict]:
        """Reconstruct an agent's full conversation: inherited branch + its purpose
        + its own model outputs (which carry any code it wrote)."""
        purpose = self._purpose_text(dict(agent_row))
        own = [{"role": "assistant", "content": m["content"]}
               for m in self.ctx.db.get_messages(agent_row["id"])]
        return inherited + [{"role": "user", "content": purpose}] + own

    def run_code_pipeline(self, code_agent_id: str, inherited: list[dict]) -> dict:
        """A code work-unit run as three sequential models, each fed the previous:
        coding_agent -> testing_agent -> philosopher (spec: change the nature of recursion)."""
        ctx, db = self.ctx, self.ctx.db
        code_row = db.get_agent(code_agent_id)
        orig_task = code_row["task"]

        # Stage 1: the coding model writes + self-checks + runs the code.
        code_res = self.run_agent(code_agent_id, inherited)
        stage1 = self._agent_conversation(db.get_agent(code_agent_id), inherited)

        # Stage 2: the code-checker verifies spec + bigger picture.
        checker = ctx.create_child(
            parent=code_row, title="Check the code against spec and the bigger picture",
            task=("Verify the code produced above is up to spec, meets the intended goal, "
                  "and fits the bigger picture it must return into.\nORIGINAL TASK:\n" + orig_task),
            role="testing_agent", done_condition="A clear PASS/FAIL verdict on the code.",
            suggested_model=None, priority=2)
        checker_res = self.run_agent(checker["id"], stage1)
        stage2 = self._agent_conversation(db.get_agent(checker["id"]), stage1)

        # Stage 3: the philosopher verifies human-level intent and reports up.
        phil = ctx.create_child(
            parent=code_row, title="Verify the work meets the human-level goal",
            task=("Without writing code, verify the work meets the human-level goals as "
                  "intended, and report a verdict to the parent.\nORIGINAL TASK:\n" + orig_task),
            role="philosopher", done_condition="A clear verdict on whether human intent is met.",
            suggested_model=None, priority=3)
        phil_res = self.run_agent(phil["id"], stage2)

        return {
            "status": code_res.get("status", "blocked"),
            "summary": (f"code: {code_res.get('summary','')} | "
                        f"check: {checker_res.get('summary','')} | "
                        f"human-goal: {phil_res.get('summary','')}"),
            "note": (f"Code pipeline finished. CODE [{code_res.get('status')}]: "
                     f"{code_res.get('note', code_res.get('summary',''))}. "
                     f"CHECKER [{checker_res.get('status')}]: "
                     f"{checker_res.get('note', checker_res.get('summary',''))}. "
                     f"PHILOSOPHER [{phil_res.get('status')}]: "
                     f"{phil_res.get('note', phil_res.get('summary',''))}."),
            "return_note": phil_res.get("note", ""),
            "completion_percentage": code_res.get("completion_percentage", 100),
            "pipeline": {"coding_agent": code_agent_id, "testing_agent": checker["id"],
                         "philosopher": phil["id"]},
        }

    def _run_children(self, spawned: list[dict], conversation: list[dict]) -> str:
        """Run children concurrently, each inheriting the branch conversation.
        The scheduler's GPU/CPU semaphores bound actual inference; thread-per-child
        avoids pool-exhaustion deadlock when a child itself spawns grandchildren."""
        if not spawned:
            return "(no children completed)"

        results: dict[str, dict] = {}

        pipeline = self.ctx.settings.get_bool("CODE_PIPELINE_ENABLED", True)

        def _run(child):
            if child.get("role") == "coding_agent" and pipeline:
                results[child["id"]] = self.run_code_pipeline(child["id"], conversation)
            else:
                results[child["id"]] = self.run_agent(child["id"], conversation)

        if self.ctx.scheduler is None or len(spawned) == 1:
            for child in spawned:
                _run(child)
        else:
            threads = [threading.Thread(target=_run, args=(c,), daemon=True) for c in spawned]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        lines = []
        for child in spawned:
            res = results.get(child["id"], {"status": "unknown"})
            lines.append(
                f"- {child['id']} ({child.get('role','?')}) [{res.get('status')}]: "
                f"{res.get('return_note') or res.get('note') or res.get('summary','')}"
            )
        return "\n".join(lines)
