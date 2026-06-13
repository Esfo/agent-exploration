"""Chat interface + slash commands (spec sections 3, 4).

Reads user input, routes slash commands directly (no LLM call), and turns
free-text messages into root swarms driven by the progenitor agent.
"""
from __future__ import annotations

from . import ids
from .agent_loop import AgentRunner
from .progress import subtree_completion


class ChatInterface:
    def __init__(self, ctx, runner: AgentRunner):
        self.ctx = ctx
        self.runner = runner
        self.db = ctx.db
        self.last_swarm: str | None = None

    # ----- public entry -----
    def handle(self, text: str) -> bool:
        """Returns False if the session should end."""
        text = text.strip()
        if not text:
            return True
        if text.startswith("/"):
            return self._slash(text)
        self._start_swarm(text)
        return True

    # ----- swarm start -----
    def _start_swarm(self, goal: str) -> None:
        from .settings import SettingsError
        from .ollama_client import OllamaError
        swarm_id = ids.next_id("swarm")
        self.db.create_swarm(swarm_id, goal)
        self.last_swarm = swarm_id
        try:
            root = self.ctx.create_root(swarm_id, "progenitor", "Root task", goal)
        except SettingsError as e:
            self.db.update_swarm(swarm_id, status="failed")
            self.ctx.events.chat(
                f"\nCannot start swarm: {e}\n"
                "Edit settings/main.settings (DEFAULT_MODEL=...) or set MODEL: in the "
                "relevant instruction file to a model you've pulled in Ollama."
            )
            return
        self.ctx.events.chat(f"\nSwarm started: {swarm_id}\nRoot task:\n    {goal}\nCompletion: 0%")
        try:
            result = self.runner.run_agent(root["id"])
        except OllamaError as e:
            self.db.update_swarm(swarm_id, status="failed")
            self.ctx.events.chat(
                f"\nOllama call failed: {e}\n"
                "Is `ollama serve` running and the model pulled? Check OLLAMA_*_ENDPOINT "
                "in settings/main.settings."
            )
            return
        pct = subtree_completion(self.db, root["id"])
        self.db.update_swarm(swarm_id, status="complete" if result.get("status") == "complete" else "blocked",
                             completion=pct)
        self._final_summary(swarm_id, root["id"], result, pct)

    def _final_summary(self, swarm_id, root_id, result, pct) -> None:
        """Spec section 33: roll up files, commands, models, profiling, etc."""
        db = self.db
        agents = db.list_swarm_agents(swarm_id)
        files = db.conn.execute(
            "SELECT action, COUNT(*) c FROM file_events WHERE agent_id IN "
            "(SELECT id FROM agents WHERE swarm_id=?) GROUP BY action", (swarm_id,)).fetchall()
        file_summary = ", ".join(f"{r['action']}={r['c']}" for r in files) or "none"
        cmds = db.conn.execute(
            "SELECT COUNT(*) c FROM terminal_commands WHERE agent_id IN "
            "(SELECT id FROM agents WHERE swarm_id=?)", (swarm_id,)).fetchone()["c"]
        models = sorted({a["selected_model"] for a in agents})
        sandboxes = db.conn.execute(
            "SELECT COUNT(*) c FROM sandboxes WHERE agent_id IN "
            "(SELECT id FROM agents WHERE swarm_id=?)", (swarm_id,)).fetchone()["c"]
        webpages = db.conn.execute("SELECT COUNT(*) c FROM web_cache").fetchone()["c"]
        profs = db.conn.execute(
            "SELECT COUNT(*) c FROM profiling_reports WHERE agent_id IN "
            "(SELECT id FROM agents WHERE swarm_id=?)", (swarm_id,)).fetchone()["c"]
        self.ctx.events.chat(
            f"\nSwarm complete: {swarm_id}\nCompletion: {pct:.0f}%  (root status: {result.get('status')})\n"
            f"\nResult:\n    {result.get('summary') or result.get('note','')}\n"
            f"\nAgents: {len(agents)}\n"
            f"Models used: {', '.join(models)}\n"
            f"Files: {file_summary}\n"
            f"Terminal commands: {cmds}\n"
            f"Sandboxes used: {sandboxes}\n"
            f"Cached web pages: {webpages}\n"
            f"Profiling reports: {profs}\n"
            f"Remaining issues: {', '.join(result.get('remaining_issues', [])) or 'none reported'}\n"
            f"Output location: workspace/agents/<id>/work  (integrated: workspace/project)"
        )

    # ----- slash commands -----
    def _slash(self, text: str) -> bool:
        parts = text.split()
        cmd, args = parts[0], parts[1:]
        handler = {
            "/help": self._help,
            "/quit": lambda a: False,
            "/exit": lambda a: False,
            "/status": self._status,
            "/progress": self._status,
            "/agents": self._agents,
            "/tree": self._tree,
            "/models": self._models,
            "/show": self._show,
            "/show-log": self._show_log,
            "/show-settings": self._show_settings,
            "/terminals": self._terminals,
            "/sandboxes": self._sandboxes,
            "/failed": lambda a: self._by_status(("failed", "blocked")),
            "/active": lambda a: self._by_status(("running", "started", "waiting_for_children")),
            "/profile": self._profile,
            "/optimization": self._optimization,
            "/show-cache": self._show_cache,
            "/memories": self._memories,
            "/remember": self._remember,
            "/forget": self._forget,
            "/branch": self._branch,
            "/branches": self._branches,
        }.get(cmd)
        if handler is None:
            self.ctx.events.chat(f"Unknown command: {cmd}. Try /help.")
            return True
        out = handler(args)
        return False if out is False else True

    def _help(self, _a) -> None:
        self.ctx.events.chat(
            "Commands: /status /progress /agents /tree /active /failed /models "
            "/terminals /sandboxes /profile /optimization /show-cache "
            "/memories /remember <text> /forget <id> /branch <swarm_id> /branches "
            "/show <agent_id> /show-settings /help /quit\n"
            "(Any other text starts a new swarm.)"
        )

    def _by_status(self, statuses) -> None:
        if not self.last_swarm:
            self.ctx.events.chat("No swarm yet.")
            return
        rows = [a for a in self.db.list_swarm_agents(self.last_swarm) if a["status"] in statuses]
        if not rows:
            self.ctx.events.chat("(none)")
            return
        for a in rows:
            self.ctx.events.chat(f"  {a['id']} [{a['role']}] {a['status']} - {a['title']}")

    def _terminals(self, _a) -> None:
        rows = self.db.conn.execute(
            "SELECT id, agent_id, status, current_cwd FROM terminals ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
        if not rows:
            self.ctx.events.chat("No terminals.")
            return
        for r in rows:
            self.ctx.events.chat(f"  {r['id']} ({r['agent_id']}) {r['status']} cwd={r['current_cwd']}")

    def _sandboxes(self, _a) -> None:
        rows = self.db.conn.execute(
            "SELECT id, agent_id, backend, status FROM sandboxes ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
        if not rows:
            self.ctx.events.chat("No sandboxes.")
            return
        for r in rows:
            self.ctx.events.chat(f"  {r['id']} ({r['agent_id']}) {r['backend']} {r['status']}")

    def _profile(self, _a) -> None:
        rows = self.db.conn.execute(
            "SELECT id, target, baseline_runtime_ms FROM profiling_reports ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        if not rows:
            self.ctx.events.chat("No profiling reports.")
            return
        for r in rows:
            self.ctx.events.chat(f"  {r['id']} {r['target']} baseline={r['baseline_runtime_ms']}ms")

    def _optimization(self, _a) -> None:
        rows = self.db.conn.execute(
            "SELECT id, target, improvement, before_runtime_ms, after_runtime_ms"
            " FROM optimization_reports ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        if not rows:
            self.ctx.events.chat("No optimization reports.")
            return
        for r in rows:
            self.ctx.events.chat(
                f"  {r['id']} {r['target']} {r['before_runtime_ms']}→{r['after_runtime_ms']}ms "
                f"({r['improvement']})")

    def _memories(self, _a) -> None:
        if self.ctx.memory is None:
            self.ctx.events.chat("Memory not enabled.")
            return
        mems = self.ctx.memory.all()
        if not mems:
            self.ctx.events.chat("No memories.")
            return
        for m in mems:
            flag = "on " if m["enabled"] else "off"
            self.ctx.events.chat(f"  [{flag}] {m['id']} ({m['scope']}) {m['text']}")

    def _remember(self, args) -> None:
        if self.ctx.memory is None or not args:
            self.ctx.events.chat("Usage: /remember <text>   (optionally start with scope= )")
            return
        scope = "global"
        if args and args[0].startswith("scope="):
            scope = args[0].split("=", 1)[1]
            args = args[1:]
        mid = self.ctx.memory.add(" ".join(args), scope=scope)
        self.ctx.events.chat(f"Remembered {mid} (scope={scope}).")

    def _forget(self, args) -> None:
        if self.ctx.memory is None or not args:
            self.ctx.events.chat("Usage: /forget <memory_id>   (disables it)")
            return
        ok = self.ctx.memory.set_enabled(args[0], False)
        self.ctx.events.chat(f"Disabled {args[0]}." if ok else f"No such memory {args[0]}.")

    def _branch(self, args) -> None:
        if self.ctx.branch is None or not args:
            self.ctx.events.chat("Usage: /branch <swarm_id> [note...]")
            return
        note = " ".join(args[1:]) if len(args) > 1 else ""
        res = self.ctx.branch.branch(args[0], note=note)
        if res["status"] == "ok":
            self.ctx.events.chat(
                f"Branched {args[0]} -> {res['branch_swarm_id']} "
                f"({res['copied_messages']} messages copied).")
        else:
            self.ctx.events.chat(f"Branch failed: {res.get('detail')}")

    def _branches(self, _a) -> None:
        if self.ctx.branch is None:
            self.ctx.events.chat("Branching not enabled.")
            return
        for b in self.ctx.branch.list_branches():
            self.ctx.events.chat(
                f"  {b['id']} [{b['status']}] {b['completion_percentage']:.0f}% "
                f"- {b['user_goal'][:60]}")

    def _show_cache(self, _a) -> None:
        rows = self.db.conn.execute(
            "SELECT id, url, fetched_at FROM web_cache ORDER BY fetched_at DESC LIMIT 30"
        ).fetchall()
        if not rows:
            self.ctx.events.chat("Web cache empty.")
            return
        for r in rows:
            self.ctx.events.chat(f"  {r['id'][:12]} {r['url']} ({r['fetched_at']})")

    def _status(self, _a) -> None:
        if not self.last_swarm:
            self.ctx.events.chat("No swarm yet.")
            return
        sw = self.db.get_swarm(self.last_swarm)
        agents = self.db.list_swarm_agents(self.last_swarm)
        by_status: dict[str, int] = {}
        for a in agents:
            by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
        self.ctx.events.chat(
            f"Swarm {sw['id']}: {sw['status']} ({sw['completion_percentage']:.0f}%)\n"
            f"  Agents: {len(agents)} [{breakdown}]"
        )

    def _agents(self, _a) -> None:
        if not self.last_swarm:
            self.ctx.events.chat("No swarm yet.")
            return
        for a in self.db.list_swarm_agents(self.last_swarm):
            self.ctx.events.chat(
                f"  {a['id']} d{a['depth']} {a['role']:<11} {a['status']:<18} "
                f"{a['completion_percentage']:.0f}%  {a['title']}"
            )

    def _tree(self, _a) -> None:
        if not self.last_swarm:
            self.ctx.events.chat("No swarm yet.")
            return
        agents = self.db.list_swarm_agents(self.last_swarm)
        by_parent: dict[str | None, list] = {}
        for a in agents:
            by_parent.setdefault(a["parent_agent_id"], []).append(a)

        def walk(pid, indent):
            for a in by_parent.get(pid, []):
                self.ctx.events.chat(
                    f"{'  '*indent}{a['id']} [{a['role']}] {a['status']} "
                    f"{a['completion_percentage']:.0f}% - {a['title']}"
                )
                walk(a["id"], indent + 1)

        walk(None, 0)

    def _models(self, _a) -> None:
        if not self.last_swarm:
            self.ctx.events.chat("No swarm yet.")
            return
        seen = {}
        for a in self.db.list_swarm_agents(self.last_swarm):
            seen.setdefault(a["role"], a["selected_model"])
        for role, model in seen.items():
            self.ctx.events.chat(f"  {role}: {model}")

    def _show(self, args) -> None:
        if not args:
            self.ctx.events.chat("Usage: /show <agent_id>")
            return
        a = self.db.get_agent(args[0])
        if not a:
            self.ctx.events.chat(f"No such agent: {args[0]}")
            return
        res = self.db.get_agent_result(a["id"])
        self.ctx.events.chat(
            f"{a['id']} [{a['role']}] {a['status']} {a['completion_percentage']:.0f}%\n"
            f"  Model: {a['selected_model']} ({a['model_source']}, {a['execution_class']}, ctx={a['num_ctx']})\n"
            f"  Task: {a['task']}\n"
            f"  Dir: {a['assigned_directory']}\n"
            f"  Result: {res['summary'] if res else '(unfinished)'}"
        )

    def _show_log(self, args) -> None:
        """Dump an agent's raw model output + tool calls — for debugging what
        the model actually emitted."""
        if not args:
            self.ctx.events.chat("Usage: /show-log <agent_id>")
            return
        aid = args[0]
        msgs = self.db.get_messages(aid)
        if not msgs:
            self.ctx.events.chat(f"No messages for {aid}.")
            return
        for m in msgs:
            if m["role"] == "assistant":
                self.ctx.events.chat(f"\n--- model output ---\n{m['content']}")
            else:
                self.ctx.events.chat(f"\n--- fed back to model ---\n{m['content'][:600]}")
        calls = self.db.conn.execute(
            "SELECT tool_name, status, result_json FROM tool_calls WHERE agent_id=? ORDER BY id", (aid,)
        ).fetchall()
        self.ctx.events.chat("\n--- tool calls ---")
        for c in calls:
            self.ctx.events.chat(f"  {c['tool_name']} -> {c['status']}: {(c['result_json'] or '')[:200]}")
        if not calls:
            self.ctx.events.chat("  (no tool calls executed)")

    def _show_settings(self, _a) -> None:
        s = self.ctx.settings
        keys = ["RUNTIME_NAME", "RUNTIME_VERSION", "DEFAULT_MODEL", "MAX_RECURSION_DEPTH",
                "MAX_TOTAL_AGENTS_PER_SWARM", "MAX_AUTO_NUM_CTX", "SANDBOX_BACKEND"]
        for k in keys:
            self.ctx.events.chat(f"  {k}={s.get(k)}")
