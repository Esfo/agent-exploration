"""Path guard (spec section 18).

Confines every file operation to an allow-list of root directories. Resolves
symlinks and rejects parent-traversal escapes. The LLM is *prompted* to stay in
its directory; this is the code that actually enforces it.
"""
from __future__ import annotations

from pathlib import Path


class PathDenied(Exception):
    pass


def _resolve(p: str | Path, base: Path) -> Path:
    p = Path(p)
    if not p.is_absolute():
        p = base / p
    # resolve() collapses .. and follows symlinks; strict=False so new files resolve.
    return p.resolve()


def is_within(target: Path, root: Path) -> bool:
    root = root.resolve()
    return target == root or root in target.parents


def confine(name: str | Path, jail_root: str | Path) -> Path:
    """Force a caller-supplied name INTO the jail directory (spec section 18).

    The agent never decides where a file lands — Python does. Any leading
    slashes, drive letters, and '..' segments are stripped, the remainder is
    joined under jail_root, and the result is hard-asserted to be inside the
    jail. This cannot escape; it can only clamp. Used for all writes/deletes.
    """
    jail = Path(jail_root).resolve()
    parts: list[str] = []
    for part in Path(str(name)).parts:
        if part in ("/", "\\", "..", "."):
            continue
        if len(part) > 1 and part.endswith(":"):  # drive letter like C:
            continue
        parts.append(part)
    if not parts:
        raise PathDenied(f"empty/invalid filename after sanitization: {name!r}")
    target = jail.joinpath(*parts).resolve()
    if not is_within(target, jail):
        # Last-ditch: collapse to a basename inside the jail.
        target = (jail / Path(str(name)).name).resolve()
    if not is_within(target, jail):  # must never happen; hard guarantee
        raise PathDenied(f"could not confine {name!r} within {jail}")
    return target


def check(candidate: str | Path, *, base: Path, allowed_roots: list[Path],
          op: str = "access") -> Path:
    """Return the resolved path if it is inside an allowed root, else raise."""
    target = _resolve(candidate, base)
    for root in allowed_roots:
        if is_within(target, root):
            return target
    raise PathDenied(
        f"{op} denied: {target} is outside allowed roots "
        f"{[str(r) for r in allowed_roots]}"
    )


def writable_roots(settings, agent_row) -> list[Path]:
    """Roots an agent may write to. Workers: their own work/output dir.
    Integrators: also the project dir (spec section 18)."""
    work = Path(agent_row["assigned_directory"]).resolve()
    agent_base = work.parent  # workspace/agents/<id>
    roots = [work, agent_base / "output"]
    if agent_row["role"] == "integrator" and settings.get_bool("ALLOW_INTEGRATOR_WRITE_PROJECT_DIR", True):
        roots.append(settings.path("PROJECT_DIR"))
    return roots


def readable_roots(settings, agent_row) -> list[Path]:
    work = Path(agent_row["assigned_directory"]).resolve()
    agent_base = work.parent
    roots = [
        work,
        agent_base / "input",
        agent_base / "output",
        settings.path("PROJECT_SNAPSHOT_DIR"),
        settings.path("SHARED_READONLY_DIR"),
        settings.path("WEB_CACHE_DIR"),
    ]
    if agent_row["role"] == "integrator":
        roots.append(settings.path("PROJECT_DIR"))
    return roots
