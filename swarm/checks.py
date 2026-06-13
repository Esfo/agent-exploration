"""Finish-gate check runner (user-list design).

Each instruction file is an ordered list of checks for the process it is named
after. When an agent tries to finish "complete", the runtime walks the checks
for that agent's role one-by-one (global + safety + role files). Each check is:
  - deterministic, if it carries an [[auto:KEY]] tag mapped here, OR
  - judged by the model otherwise.
The first failing check (in order) blocks the finish and is returned so the
agent can fix it (or decide it needs a new swarm, or defer).
"""
from __future__ import annotations

import json
import os

from .instructions import parse_instruction_file
from .tool_parser import _loose_json

# ---- deterministic checks: key -> fn(ctx, agent_id) -> (passed, detail) ----
AUTO_CHECKS = {}


def _auto(key):
    def deco(fn):
        AUTO_CHECKS[key] = fn
        return fn
    return deco


@_auto("created_a_file")
def _created_a_file(ctx, agent_id):
    n = ctx.db.conn.execute(
        "SELECT COUNT(*) c FROM file_events WHERE agent_id=? AND action IN ('created','modified')",
        (agent_id,)).fetchone()["c"]
    return (n > 0, f"{n} file(s) written" if n else "no files were created")


@_auto("validation_passed")
def _validation_passed(ctx, agent_id):
    rows = ctx.db.conn.execute(
        "SELECT result_json FROM tool_calls WHERE agent_id=? AND tool_name IN ('python','shell')",
        (agent_id,)).fetchall()
    for r in rows:
        try:
            d = json.loads(r["result_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if d.get("exit_code") == 0:
            return (True, "a python/shell command exited 0")
    tc = ctx.db.conn.execute(
        "SELECT COUNT(*) c FROM terminal_commands WHERE agent_id=? AND exit_code=0",
        (agent_id,)).fetchone()["c"]
    if tc > 0:
        return (True, "a terminal command exited 0")
    return (False, "no successful validation command (exit 0) was run")


@_auto("tests_present")
def _tests_present(ctx, agent_id):
    rows = ctx.db.conn.execute(
        "SELECT path FROM file_events WHERE agent_id=? AND action IN ('created','modified')",
        (agent_id,)).fetchall()
    for r in rows:
        name = os.path.basename(r["path"])
        if name.startswith("test_") or name.endswith("_test.py"):
            return (True, f"found {name}")
    return (False, "no test_*.py file was created")


@_auto("cwd_clean")
def _cwd_clean(ctx, agent_id):
    bad = ctx.db.conn.execute(
        "SELECT COUNT(*) c FROM terminal_commands WHERE agent_id=? AND cwd_guard_passed=0",
        (agent_id,)).fetchone()["c"]
    return (bad == 0, "all terminal commands stayed in the jail" if bad == 0
            else f"{bad} command(s) left the jail")


@_auto("no_failed_commands")
def _no_failed_commands(ctx, agent_id):
    bad = ctx.db.conn.execute(
        "SELECT COUNT(*) c FROM terminal_commands WHERE agent_id=? AND exit_code NOT IN (0)",
        (agent_id,)).fetchone()["c"]
    return (bad == 0, "no failing commands" if bad == 0 else f"{bad} command(s) failed")


def available_auto_keys() -> list[str]:
    return sorted(AUTO_CHECKS)


# ---- gathering the checks that gate a role ----
def _gather(settings, role):
    """Ordered (file_name, Check) for every instruction file that gates this
    role — the same set injected into its context (global + role + per-tool)."""
    from .context_builder import instruction_keys_for
    out = []
    for key in instruction_keys_for(role):
        rel = settings.get(key)
        if not rel:
            continue
        path = settings.root / rel
        if not path.exists():
            continue
        inst = parse_instruction_file(path)
        for chk in inst.checks:
            out.append((path.name, chk))
    return out


# ---- model evaluation of the non-deterministic checks (one call) ----
def _model_eval(ctx, agent, history, model_checks):
    """Return {position: (passed, reason)}. Defaults to PASS on any failure to
    parse, so a flaky local model never deadlocks the gate (auto checks remain
    the reliable gate)."""
    if not model_checks:
        return {}
    listing = "\n".join(f"{pos}. {text}" for pos, text in model_checks)
    convo = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-12:])
    system = ("You are verifying whether an agent implemented its process correctly. "
              "For each numbered check, decide PASS or FAIL based ONLY on the work shown. "
              'Return JSON: {"results":[{"n":1,"verdict":"PASS","reason":".."}]}.')
    user = f"WORK SO FAR:\n{convo}\n\nCHECKS:\n{listing}"
    try:
        opts = {"num_ctx": int(agent["num_ctx"] or 8192),
                "num_predict": 1024, "temperature": 0.0}
        if ctx.scheduler is not None:
            with ctx.scheduler.inference_slot(agent["execution_class"], agent["id"]):
                resp = ctx.client.chat(endpoint=agent["ollama_endpoint"],
                                       model=agent["selected_model"],
                                       messages=[{"role": "system", "content": system},
                                                 {"role": "user", "content": user}],
                                       options=opts)
        else:
            resp = ctx.client.chat(endpoint=agent["ollama_endpoint"],
                                   model=agent["selected_model"],
                                   messages=[{"role": "system", "content": system},
                                             {"role": "user", "content": user}],
                                   options=opts)
        data, err = _loose_json(resp.content)
        if err or not isinstance(data, dict):
            return {}
        out = {}
        for item in data.get("results", []):
            try:
                out[int(item["n"])] = (str(item.get("verdict", "PASS")).upper() != "FAIL",
                                       str(item.get("reason", "")))
            except (KeyError, ValueError, TypeError):
                continue
        return out
    except Exception:  # noqa: BLE001 - never let the gate crash the run
        return {}


def run_gate(ctx, agent, history):
    """Walk the role's checks in order. Return (passed, failing_text, detail, file)."""
    checks = _gather(ctx.settings, agent["role"])
    if not checks:
        return (True, None, None, None)

    model_checks = [(chk.position, chk.text) for _, chk in checks
                    if not (chk.auto_key and chk.auto_key in AUTO_CHECKS)]
    use_model = ctx.settings.get_bool("CHECK_GATE_MODEL_EVAL", True)
    verdicts = _model_eval(ctx, agent, history, model_checks) if use_model else {}

    for fname, chk in checks:
        if chk.auto_key and chk.auto_key in AUTO_CHECKS:
            passed, detail = AUTO_CHECKS[chk.auto_key](ctx, agent["id"])
        else:
            passed, detail = verdicts.get(chk.position, (True, "not evaluated"))
        if not passed:
            return (False, chk.text, detail, fname)
    return (True, None, None, None)
