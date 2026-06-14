"""Web fetch + on-disk cache (spec section 24).

Cache layout:
    cache/web/
        pages/<sha256_url>/
            metadata.json
            raw.html
            extracted.txt
            fetched_at.txt

Fetches go through web_guard (SSRF protection). Pages are reused when fresh.
The DB web_cache table indexes entries. Extraction is a dependency-free HTML
tag-strip — good enough for feeding docs to a model.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .runtime_guards.web_guard import WebDenied, check_url

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS = re.compile(r"\n\s*\n\s*\n+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _sha(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def extract_text(html: str) -> str:
    no_scripts = _SCRIPT_STYLE.sub(" ", html)
    text = _unescape(_TAG.sub(" ", no_scripts))
    lines = [ln.strip() for ln in text.splitlines()]
    return _WS.sub("\n\n", "\n".join(ln for ln in lines if ln))


def _unescape(s: str) -> str:
    return (s.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))


def extract_title(html: str) -> str:
    m = _TITLE.search(html)
    return _unescape(_TAG.sub("", m.group(1))).strip() if m else ""


class WebCache:
    def __init__(self, settings, db):
        self.s = settings
        self.db = db
        self.root = settings.path("WEB_CACHE_DIR")
        self.pages = self.root / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)

    def _entry_dir(self, url: str) -> Path:
        return self.pages / _sha(url)

    def lookup(self, url: str, max_age_hours: float) -> dict | None:
        d = self._entry_dir(url)
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        age_h = (time.time() - meta.get("fetched_at_epoch", 0)) / 3600
        if age_h > max_age_hours:
            return None
        meta["_cache_hit"] = True
        meta["_dir"] = str(d)
        return meta

    def fetch(self, url: str, purpose: str, agent_id: str,
              max_age_hours: float | None = None, reuse: bool = True) -> dict:
        max_age = max_age_hours if max_age_hours is not None else \
            (self.s.get_int("WEB_DEFAULT_MAX_AGE_HOURS", 168) or 168)

        if reuse:
            hit = self.lookup(url, max_age)
            if hit:
                return {"status": "ok", "cache_hit": True, "url": url,
                        "title": hit.get("title", ""), "cache_id": _sha(url),
                        "extracted_path": str(Path(hit["_dir"]) / "extracted.txt")}

        try:
            check_url(url, allow_http=self.s.get_bool("WEB_ALLOW_HTTP", False),
                      block_private=self.s.get_bool("WEB_BLOCK_PRIVATE_IPS", True))
        except WebDenied as e:
            return {"status": "error", "failure": "web_fetch_failed", "detail": str(e)}

        timeout = self.s.get_int("WEB_DEFAULT_TIMEOUT_SECONDS", 20) or 20
        max_mb = self.s.get_int("WEB_MAX_DOWNLOAD_MB", 10) or 10
        req = urllib.request.Request(url, headers={"User-Agent": "recursive_local_swarm/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read(max_mb * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"status": "error", "failure": "web_fetch_failed", "detail": str(e)}

        truncated = len(raw) > max_mb * 1024 * 1024
        raw = raw[: max_mb * 1024 * 1024]
        html = raw.decode("utf-8", errors="replace")
        title = extract_title(html)
        extracted = extract_text(html)

        d = self._entry_dir(url)
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw.html").write_text(html, encoding="utf-8")
        (d / "extracted.txt").write_text(extracted, encoding="utf-8")
        now_iso = datetime.now(timezone.utc).isoformat()
        (d / "fetched_at.txt").write_text(now_iso, encoding="utf-8")
        meta = {
            "url": url, "fetched_at": now_iso, "fetched_at_epoch": time.time(),
            "status_code": status_code, "content_type": content_type,
            "sha256": _sha(url), "title": title, "purpose": purpose,
            "used_by_agents": [agent_id], "truncated": truncated,
        }
        (d / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        self.db.conn.execute(
            "INSERT OR REPLACE INTO web_cache (id, url, fetched_at, status_code, content_type,"
            " raw_path, extracted_path, metadata_json) VALUES (?,?,?,?,?,?,?,?)",
            (_sha(url), url, now_iso, status_code, content_type,
             str(d / "raw.html"), str(d / "extracted.txt"), json.dumps(meta)),
        )
        self.db.conn.commit()

        return {"status": "ok", "cache_hit": False, "url": url, "title": title,
                "cache_id": _sha(url), "status_code": status_code,
                "extracted_path": str(d / "extracted.txt"), "truncated": truncated}

    def search(self, query: str) -> list[dict]:
        q = (query or "").lower()
        rows = self.db.conn.execute(
            "SELECT id, url, fetched_at, content_type FROM web_cache ORDER BY fetched_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            if not q or q in r["url"].lower():
                out.append({"cache_id": r["id"], "url": r["url"], "fetched_at": r["fetched_at"]})
        return out

    def read(self, cache_id: str, max_chars: int = 20000) -> dict:
        row = self.db.conn.execute(
            "SELECT * FROM web_cache WHERE id=?", (cache_id,)
        ).fetchone()
        if not row:
            return {"status": "error", "failure": "not_found", "detail": cache_id}
        path = Path(row["extracted_path"])
        if not path.exists():
            return {"status": "error", "failure": "not_found", "detail": str(path)}
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"status": "ok", "url": row["url"], "content": text[:max_chars],
                "truncated": len(text) > max_chars}
