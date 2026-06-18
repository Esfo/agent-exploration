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

DOC_MANIFEST = "INTEGRATED.md"


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


def _unique_dest(project_dir: Path, name: str) -> Path:
    dest = project_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while (project_dir / f"{stem}_{i}{suffix}").exists():
        i += 1
    return project_dir / f"{stem}_{i}{suffix}"


def run_zipper(ctx, zipper: dict, agents: list[dict], *, task_list: str = "",
               goal: str = "") -> ZipperResult:
    """Integrate the group's deliverables into PROJECT_DIR and write a doc manifest.

    ``zipper`` is an already-created zipper_agent record (carries the model fields).
    ``agents`` are the converged group whose work dirs hold the deliverables.
    """
    res = ZipperResult()

    project_dir = ctx.settings.path("PROJECT_DIR")
    project_dir.mkdir(parents=True, exist_ok=True)

    # System prompt for the YES/NO gate comes from the zipper's instruction file.
    sys_txt = "You finalize a project. Answer only YES or NO."
    rel = ctx.settings.get("INSTRUCTION_ZIPPER")
    if rel and (ctx.settings.root / rel).exists():
        sys_txt = parse_instruction_file(ctx.settings.root / rel).render() or sys_txt

    integrated_meta: list[tuple[str, str]] = []  # (dest_name, source_role)
    for agent in agents:
        role = agent.get("role", "?")
        for src in _candidate_files(agent):
            q = (f"Goal: {goal or '(unspecified)'}\n"
                 f"A {role} agent produced the file '{src.name}'. "
                 "Should it be integrated into the finished project?")
            if not _ask_yes(ctx, zipper, sys_txt, q):
                res.skipped.append(str(src))
                continue
            dest = _unique_dest(project_dir, src.name)
            try:
                shutil.copy2(src, dest)
            except Exception:  # noqa: BLE001
                res.skipped.append(str(src))
                continue
            res.integrated.append(str(dest))
            integrated_meta.append((dest.name, role))

    res.doc_path = _write_manifest(project_dir, integrated_meta, goal, task_list)
    res.summary = (f"zipper integrated {len(res.integrated)} file(s) into "
                   f"{project_dir.name}/, skipped {len(res.skipped)}.")
    return res


def _write_manifest(project_dir: Path, integrated_meta: list[tuple[str, str]],
                    goal: str, task_list: str) -> str:
    """Generate the project doc manifest if missing, otherwise update it."""
    manifest = project_dir / DOC_MANIFEST
    existing = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
    header = "# Integrated project artifacts\n"
    lines = [header] if not existing else [existing.rstrip() + "\n"]
    if goal:
        lines.append(f"\n## {goal}\n")
    if task_list:
        lines.append(f"\nTask list before spawn:\n{task_list.strip()}\n")
    if integrated_meta:
        lines.append("\nFiles integrated this pass:\n")
        for name, role in integrated_meta:
            lines.append(f"- `{name}` (from {role})\n")
    else:
        lines.append("\n(no new files integrated this pass)\n")
    manifest.write_text("".join(lines), encoding="utf-8")
    return str(manifest)
