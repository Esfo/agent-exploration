"""Command guard (spec section 19).

Hard-coded Python risk checks on command-like tool requests. This is the real
safety boundary together with the executor/sandbox — the model's own answers to
the command-questioning prompts are advisory, never trusted as enforcement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (regex, reason). Matched case-insensitively against the raw command string.
BLOCKED_PATTERNS = [
    (r"\bsudo\b", "privilege escalation (sudo)"),
    (r"\bsu\b", "privilege escalation (su)"),
    (r"\bchmod\s+-?R?\s*0?777\b", "world-writable chmod"),
    (r"\bchown\b", "ownership change"),
    (r"\bmount\b", "filesystem mount"),
    (r"\bumount\b", "filesystem unmount"),
    (r"\bmkfs\b", "filesystem format"),
    (r"\bdd\b", "raw disk write (dd)"),
    (r"\bshutdown\b", "host shutdown"),
    (r"\breboot\b", "host reboot"),
    (r"\bsystemctl\b", "host service control"),
    (r"\bservice\b\s+\w+\s+(stop|start|restart)", "host service control"),
    (r"docker\.sock", "docker socket access"),
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+/(?:\s|$)", "recursive delete of root"),
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\w", "recursive force delete of absolute path"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", "fork bomb"),
    (r"(curl|wget)\b[^|]*\|\s*(bash|sh|zsh)\b", "pipe-to-shell of remote content"),
    (r">\s*/dev/sd[a-z]", "raw block device write"),
]

# Patterns that require network; flagged when network is disabled.
NETWORK_PATTERNS = [r"\bcurl\b", r"\bwget\b", r"\bping\b", r"\bnc\b", r"\bnmap\b",
                   r"\bssh\b", r"\bscp\b", r"\bpip\s+install\b", r"\bapt\b", r"\bapt-get\b"]


@dataclass
class GuardResult:
    decision: str          # "allow" | "block"
    reasons: list[str]
    missing_fields: list[str]

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


REQUIRED_FIELDS = ("reason", "expected_result", "destructive_risk_answer")


def check_command(command: str, args: dict | None = None, *,
                  require_fields: bool = True, **_ignored) -> GuardResult:
    """Hard safety check: required command-questioning fields + catastrophic-host
    patterns. Network is governed by the sandbox (SANDBOX_NETWORK_DEFAULT), not
    by a per-tool flag, so there is no network check here."""
    reasons: list[str] = []
    missing: list[str] = []
    args = args or {}

    if require_fields:
        for f in REQUIRED_FIELDS:
            if not str(args.get(f, "")).strip():
                missing.append(f)

    cmd = command or ""
    for pat, why in BLOCKED_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            reasons.append(why)

    if reasons or missing:
        return GuardResult("block", reasons, missing)
    return GuardResult("allow", [], [])
