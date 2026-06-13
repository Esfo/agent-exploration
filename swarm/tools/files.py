"""File tools (spec section 21): list_files, read_file, write_file,
append_file, delete_file. Every path passes through the path guard before any
operation, and every mutation is recorded as a file_event.
"""
from __future__ import annotations

from pathlib import Path

from ..runtime_guards import path_guard


def _agent(ctx, agent_id):
    a = ctx.db.get_agent(agent_id)
    if a is None:
        raise path_guard.PathDenied("no such agent")
    return a


def _base(agent) -> Path:
    return Path(agent["assigned_directory"]).resolve()


def list_files(ctx, agent_id: str, args: dict) -> dict:
    agent = _agent(ctx, agent_id)
    base = _base(agent)
    rel = args.get("path", ".")
    try:
        target = path_guard.check(rel, base=base,
                                  allowed_roots=path_guard.readable_roots(ctx.settings, agent),
                                  op="list")
    except path_guard.PathDenied as e:
        return {"status": "error", "failure": "path_denied", "detail": str(e)}
    if not target.exists():
        return {"status": "ok", "entries": [], "note": "path does not exist yet"}
    entries = []
    if target.is_dir():
        for p in sorted(target.iterdir()):
            entries.append(p.name + ("/" if p.is_dir() else ""))
    else:
        entries.append(target.name)
    return {"status": "ok", "entries": entries}


def read_file(ctx, agent_id: str, args: dict) -> dict:
    agent = _agent(ctx, agent_id)
    base = _base(agent)
    try:
        target = path_guard.check(args.get("path", ""), base=base,
                                  allowed_roots=path_guard.readable_roots(ctx.settings, agent),
                                  op="read")
    except path_guard.PathDenied as e:
        return {"status": "error", "failure": "path_denied", "detail": str(e)}
    if not target.exists() or not target.is_file():
        return {"status": "error", "failure": "not_found", "detail": str(target)}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"status": "error", "failure": "read_failed", "detail": str(e)}
    max_kb = ctx.settings.get_int("MAX_FILE_WRITE_MB", 5) or 5
    limit = max_kb * 1024 * 1024
    truncated = len(content) > limit
    ctx.db.conn.execute(
        "INSERT INTO file_events (agent_id, action, path, created_at) VALUES (?,?,?,datetime('now'))",
        (agent_id, "read", str(target)),
    )
    ctx.db.conn.commit()
    return {"status": "ok", "path": str(target), "content": content[:limit], "truncated": truncated}


def write_file(ctx, agent_id: str, args: dict) -> dict:
    agent = _agent(ctx, agent_id)
    base = _base(agent)
    rel = args.get("path", "")
    content = args.get("content", "")
    if not rel:
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'path'"}
    try:
        target = path_guard.check(rel, base=base,
                                  allowed_roots=path_guard.writable_roots(ctx.settings, agent),
                                  op="write")
    except path_guard.PathDenied as e:
        return {"status": "error", "failure": "path_denied", "detail": str(e)}

    max_mb = ctx.settings.get_int("MAX_FILE_WRITE_MB", 5) or 5
    if len(content.encode("utf-8")) > max_mb * 1024 * 1024:
        return {"status": "error", "failure": "file_too_large",
                "detail": f"exceeds MAX_FILE_WRITE_MB={max_mb}"}

    existed = target.exists()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"status": "error", "failure": "write_failed", "detail": str(e)}

    action = "modified" if existed else "created"
    ctx.db.conn.execute(
        "INSERT INTO file_events (agent_id, action, path, created_at) VALUES (?,?,?,datetime('now'))",
        (agent_id, action, str(target)),
    )
    ctx.db.conn.commit()
    return {"status": "ok", "path": str(target), "action": action, "bytes": len(content)}


def append_file(ctx, agent_id: str, args: dict) -> dict:
    agent = _agent(ctx, agent_id)
    base = _base(agent)
    rel = args.get("path", "")
    content = args.get("content", "")
    try:
        target = path_guard.check(rel, base=base,
                                  allowed_roots=path_guard.writable_roots(ctx.settings, agent),
                                  op="append")
    except path_guard.PathDenied as e:
        return {"status": "error", "failure": "path_denied", "detail": str(e)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return {"status": "error", "failure": "write_failed", "detail": str(e)}
    ctx.db.conn.execute(
        "INSERT INTO file_events (agent_id, action, path, created_at) VALUES (?,?,?,datetime('now'))",
        (agent_id, "appended", str(target)),
    )
    ctx.db.conn.commit()
    return {"status": "ok", "path": str(target), "action": "appended"}


def delete_file(ctx, agent_id: str, args: dict) -> dict:
    agent = _agent(ctx, agent_id)
    base = _base(agent)
    rel = args.get("path", "")
    try:
        target = path_guard.check(rel, base=base,
                                  allowed_roots=path_guard.writable_roots(ctx.settings, agent),
                                  op="delete")
    except path_guard.PathDenied as e:
        return {"status": "error", "failure": "path_denied", "detail": str(e)}
    if not target.exists():
        return {"status": "error", "failure": "not_found", "detail": str(target)}
    if target.is_dir():
        return {"status": "error", "failure": "refused", "detail": "will not delete directories"}

    soft = ctx.settings.get_bool("SOFT_DELETE", True)
    if soft:
        trash = base.parent / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / target.name
        try:
            target.replace(dest)
        except OSError as e:
            return {"status": "error", "failure": "delete_failed", "detail": str(e)}
        location = str(dest)
    else:
        try:
            target.unlink()
        except OSError as e:
            return {"status": "error", "failure": "delete_failed", "detail": str(e)}
        location = None

    ctx.db.conn.execute(
        "INSERT INTO file_events (agent_id, action, path, created_at) VALUES (?,?,?,datetime('now'))",
        (agent_id, "deleted", str(target)),
    )
    ctx.db.conn.commit()
    return {"status": "ok", "deleted": str(target), "soft_deleted_to": location,
            "reason": args.get("reason", "")}
