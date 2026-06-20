"""Run a recognised code block inside the sandbox.

Each language maps to (source filename, shell command). The source is written
into the agent's work directory (mounted at /agent in Docker) and run via the
executor's ``run_shell``. Only what the program prints is returned.
"""
from __future__ import annotations

from pathlib import Path

# canonical lang -> (source filename, command run from /agent)
LANG_RUN: dict[str, tuple[str, str]] = {
    "python": ("main.py", "python3 main.py"),
    "node": ("main.js", "node main.js"),
    "ts": ("main.ts", "ts-node main.ts"),
    "ruby": ("main.rb", "ruby main.rb"),
    "go": ("main.go", "go run main.go"),
    "rust": ("main.rs", "rustc main.rs -o prog && ./prog"),
    "c": ("main.c", "cc main.c -o prog && ./prog"),
    "cpp": ("main.cpp", "c++ main.cpp -o prog && ./prog"),
    "java": ("Main.java", "javac Main.java && java Main"),
    "kotlin": ("main.kt", "kotlinc main.kt -include-runtime -d prog.jar && java -jar prog.jar"),
    "scala": ("Main.scala", "scala Main.scala"),
    "swift": ("main.swift", "swift main.swift"),
    "php": ("main.php", "php main.php"),
    "perl": ("main.pl", "perl main.pl"),
    "lua": ("main.lua", "lua main.lua"),
    "r": ("main.R", "Rscript main.R"),
    "julia": ("main.jl", "julia main.jl"),
    "haskell": ("main.hs", "runghc main.hs"),
    "bash": ("main.sh", "bash main.sh"),
    "sql": ("main.sql", "sqlite3 :memory: < main.sql"),
}


def run_code(executor, lang: str, code: str, work_dir: Path, timeout: int = 60):
    """Write ``code`` for ``lang`` into ``work_dir`` and run it in the sandbox.
    Returns the executor's ExecResult, or ``None`` if the language is unknown."""
    spec = LANG_RUN.get(lang)
    if spec is None:
        return None
    filename, command = spec
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / filename).write_text(code, encoding="utf-8")
    return executor.run_shell(command, work_dir, timeout)


def format_result(result) -> str:
    """Render an ExecResult as the text returned to an agent via RETURN_OUTPUT."""
    if result is None:
        return "(no runnable code block was found)"
    parts = []
    if result.stdout:
        parts.append("stdout:\n" + result.stdout)
    if result.stderr:
        parts.append("stderr:\n" + result.stderr)
    if result.exit_code is not None:
        parts.append(f"exit code: {result.exit_code}")
    if result.timed_out:
        parts.append("(timed out)")
    return "\n".join(parts) if parts else "(no output)"
