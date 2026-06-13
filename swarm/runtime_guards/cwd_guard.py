"""CWD guard (spec section 18).

Ensures a terminal's working directory stays inside the agent jail before and
after every command. Works for both backends: the jail root is the host work
dir (subprocess) or /agent (docker).
"""
from __future__ import annotations

import posixpath


def within(pwd: str, root: str) -> bool:
    pwd = posixpath.normpath(pwd)
    root = posixpath.normpath(root)
    return pwd == root or pwd.startswith(root.rstrip("/") + "/")


def relative(pwd: str, root: str) -> str | None:
    """Return pwd relative to root ('.' for root itself), or None if outside."""
    if not within(pwd, root):
        return None
    pwd = posixpath.normpath(pwd)
    root = posixpath.normpath(root)
    if pwd == root:
        return "."
    return pwd[len(root.rstrip("/")) + 1:]
