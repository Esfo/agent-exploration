"""The zipper process: finalize a converged piece of work.

After a spawned group converges (unanimous FINISHED), the zipper takes the
finalized agent outputs and the task list that preceded the spawn and organizes
everything into the formal project area — moving deliverables out of individual
agent/test directories into ``PROJECT_DIR`` — then generates or updates the
project documentation manifest.

Per the spec the zipper is deliberately hard-coded: it asks its model a single
YES/NO question per artifact, and Python performs the actual move / doc write,
reporting "the modification has been made". The model is a gate, not an author.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .instructions import parse_instruction_file

# Files that are never project deliverables regardless of the model's opinion.
_SKIP_NAMES = {".gitkeep"}
_SKIP_SUFFIXES = {".pyc", ".log", ".tmp"}

DOC_MANIFEST = "README.md"

# Finalized work is placed by category, not in recursive per-agent directories.
# Category is decided first by the producing role, then by file extension.
CATEGORY_BY_ROLE = {
    "coding_agent": "code", "fixer": "code", "optimizer": "code",
    "integrator": "code", "testing_agent": "code", "testing": "code",
    "researcher": "research",
    "philosopher": "notes",
    "profiler": "reports", "reviewer": "reports",
    "math": "math", "physics": "math", "chemistry": "math", "economics": "reports",
}
CATEGORY_BY_EXT = {
    ".py": "code", ".js": "code", ".ts": "code", ".go": "code", ".rs": "code",
    ".c": "code", ".h": "code", ".cpp": "code", ".java": "code", ".rb": "code",
    ".sh": "code", ".sql": "code",
    ".md": "docs", ".rst": "docs", ".html": "docs", ".pdf": "docs", ".txt": "docs",
    ".ipynb": "research",
    ".tex": "math", ".csv": "reports",
}
DEFAULT_CATEGORY = "notes"

# Human-facing labels for the minimal manifest ("here's the code", "here's docs").
CATEGORY_BLURB = {
    "code": "here's the code",
    "docs": "here's the docs / pages",
    "research": "here's the research",
    "math": "here's the math",
    "reports": "here's the reports",
    "notes": "here's the notes",
}


def _category(role: str, filename: str) -> str:
    if role in CATEGORY_BY_ROLE:
        return CATEGORY_BY_ROLE[role]
    return CATEGORY_BY_EXT.get(Path(filename).suffix.lower(), DEFAULT_CATEGORY)


@dataclass
class ZipperResult:
    integrated: list[str] = field(default_factory=list)   # dest paths
    skipped: list[str] = field(default_factory=list)      # src paths
    doc_path: str | None = None
    summary: str = ""

    def as_dict(self) -> dict:
        return {"integrated": self.integrated, "skipped": self.skipped,
                "doc_path": self.doc_path, "summary": self.summary}


def _candidate_files(agent: dict) -> list[Path]:
    work = Path(agent.get("assigned_directory", "")) if agent.get("assigned_directory") else None
    if not work or not work.exists():
        return []
    out = []
    for p in sorted(work.rglob("*")):
        if not p.is_file():
            continue
        if p.name in _SKIP_NAMES or p.suffix in _SKIP_SUFFIXES:
            continue
        out.append(p)
    return out


def _parse_yes(text: str) -> bool:
    """The zipper answers YES/NO; default to NO on anything ambiguous."""
    t = (text or "").strip().lower()
    return t.startswith("yes") or t == "y"


def _ask_yes(ctx, zipper: dict, sys_txt: str, question: str) -> bool:
    msgs = [{"role": "system", "content": sys_txt},
            {"role": "user", "content": question + "\nAnswer only YES or NO."}]
    opts = {"num_ctx": int(zipper.get("num_ctx") or 8192),
            "num_predict": 16,
            "temperature": 0.0}
    try:
        if ctx.scheduler is not None:
            with ctx.scheduler.inference_slot(zipper.get("execution_class", "cpu"), zipper["id"]):
                resp = ctx.client.chat(endpoint=zipper.get("ollama_endpoint"),
                                       model=zipper.get("selected_model"), messages=msgs, options=opts)
        else:
            resp = ctx.client.chat(endpoint=zipper.get("ollama_endpoint"),
                                   model=zipper.get("selected_model"), messages=msgs, options=opts)
        try:
            ctx.db.save_model_call(zipper["id"], resp.telemetry)
        except Exception:  # noqa: BLE001
            pass
        return _parse_yes(resp.content)
    except Exception:  # noqa: BLE001 - a finalizer must never crash the swarm
        return False


def _unique_dest(category_dir: Path, name: str) -> Path:
    dest = category_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while (category_dir / f"{stem}_{i}{suffix}").exists():
        i += 1
    return category_dir / f"{stem}_{i}{suffix}"


def run_zipper(ctx, zipper: dict, agents: list[dict], *, task_list: str = "",
               goal: str = "", target_dir=None) -> ZipperResult:
    """Finalize the group's deliverables into ``target_dir`` and write the manifest.

    Work is **moved** (not copied) into per-category subdirectories
    (``code/``, ``docs/``, ``research/``, ``math/``, ``reports/``, ``notes/``) — the
    final, intended location — rather than left in recursive per-agent directories.
    ``target_dir`` defaults to ``PROJECT_DIR`` (top of the swarm); a sub-swarm passes
    its spawning agent's directory so finals bubble upward one level at a time.

    ``zipper`` is an already-created zipper_agent record (carries the model fields).
    ``agents`` are the converged group whose work dirs hold the deliverables.
    """
    res = ZipperResult()

    project_dir = Path(target_dir) if target_dir is not None else ctx.settings.path("PROJECT_DIR")
    project_dir.mkdir(parents=True, exist_ok=True)

    # System prompt for the YES/NO gate comes from the zipper's instruction file.
    sys_txt = "You finalize a project. Answer only YES or NO."
    rel = ctx.settings.get("INSTRUCTION_ZIPPER")
    if rel and (ctx.settings.root / rel).exists():
        sys_txt = parse_instruction_file(ctx.settings.root / rel).render() or sys_txt

    # category -> list of (dest_name, role)
    integrated_meta: dict[str, list[tuple[str, str]]] = {}
    for agent in agents:
        role = agent.get("role", "?")
        for src in _candidate_files(agent):
            q = (f"Goal: {goal or '(unspecified)'}\n"
                 f"A {role} agent produced the file '{src.name}'. "
                 "Should it be integrated into the finished project?")
            if not _ask_yes(ctx, zipper, sys_txt, q):
                res.skipped.append(str(src))
                continue
            category = _category(role, src.name)
            cat_dir = project_dir / category
            cat_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(cat_dir, src.name)
            try:
                shutil.move(str(src), str(dest))   # move into the final location
            except Exception:  # noqa: BLE001
                res.skipped.append(str(src))
                continue
            res.integrated.append(str(dest))
            integrated_meta.setdefault(category, []).append((dest.name, role))

    res.doc_path = _write_manifest(project_dir, integrated_meta, goal)
    res.summary = (f"zipper finalized {len(res.integrated)} file(s) into "
                   f"{project_dir.name}/ across {len(integrated_meta)} categor"
                   f"{'y' if len(integrated_meta) == 1 else 'ies'}, skipped {len(res.skipped)}.")
    return res


def _write_manifest(project_dir: Path, integrated_meta: dict[str, list[tuple[str, str]]],
                    goal: str) -> str:
    """Write a minimal, human-facing manifest: one section per category, each
    introduced by its blurb ("here's the code", "here's the docs", ...)."""
    manifest = project_dir / DOC_MANIFEST
    lines = ["# Project deliverables\n"]
    if goal:
        lines.append(f"\n_{goal}_\n")
    if not integrated_meta:
        lines.append("\n(nothing finalized yet)\n")
    for category in ("code", "docs", "research", "math", "reports", "notes"):
        items = integrated_meta.get(category)
        if not items:
            continue
        blurb = CATEGORY_BLURB.get(category, f"here's the {category}")
        lines.append(f"\n## {category}/ — {blurb}\n")
        for name, role in items:
            lines.append(f"- `{category}/{name}` (from {role})\n")
    manifest.write_text("".join(lines), encoding="utf-8")
    return str(manifest)
