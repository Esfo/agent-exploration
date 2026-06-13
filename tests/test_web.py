"""Web guard + cache, tested offline (no live network)."""
import json
import time
from pathlib import Path

import pytest

from swarm.runtime_guards.web_guard import WebDenied, check_url, _is_private_ip
from swarm.web_cache import extract_text, extract_title
from swarm import ids
from tests.conftest import MockClient, make_runtime


# ---------- web guard ----------
def test_http_blocked_by_default():
    with pytest.raises(WebDenied):
        check_url("http://example.com", allow_http=False, block_private=True)


def test_bad_scheme():
    with pytest.raises(WebDenied):
        check_url("ftp://example.com/x", allow_http=True, block_private=False)


def test_localhost_blocked():
    with pytest.raises(WebDenied):
        check_url("https://localhost/x", allow_http=False, block_private=True)


def test_metadata_ip_blocked():
    with pytest.raises(WebDenied):
        check_url("https://169.254.169.254/latest", allow_http=False, block_private=True)


def test_loopback_ip_blocked():
    # literal IP -> getaddrinfo is offline-safe
    with pytest.raises(WebDenied):
        check_url("https://127.0.0.1/x", allow_http=False, block_private=True)


def test_private_ip_helper():
    assert _is_private_ip("10.0.0.1")
    assert _is_private_ip("192.168.1.1")
    assert _is_private_ip("169.254.169.254")
    assert not _is_private_ip("8.8.8.8")


# ---------- extraction ----------
def test_extract_text_and_title():
    html = "<html><head><title>Hi &amp; Bye</title></head><body><script>x=1</script><p>Hello <b>world</b></p></body></html>"
    assert extract_title(html) == "Hi & Bye"
    text = extract_text(html)
    assert "Hello" in text and "world" in text
    assert "x=1" not in text  # script stripped


# ---------- cache hit path (no network) ----------
def _seed_cache(ctx, url, body="cached body text"):
    wc = ctx.web_cache
    d = wc._entry_dir(url)
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.html").write_text(f"<html>{body}</html>", encoding="utf-8")
    (d / "extracted.txt").write_text(body, encoding="utf-8")
    import hashlib
    cid = hashlib.sha256(url.encode()).hexdigest()
    meta = {"url": url, "fetched_at": "now", "fetched_at_epoch": time.time(),
            "status_code": 200, "content_type": "text/html", "sha256": cid,
            "title": "Cached", "purpose": "t", "used_by_agents": ["a"]}
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    ctx.db.conn.execute(
        "INSERT OR REPLACE INTO web_cache (id,url,fetched_at,status_code,content_type,raw_path,extracted_path,metadata_json)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (cid, url, "now", 200, "text/html", str(d / "raw.html"), str(d / "extracted.txt"), json.dumps(meta)),
    )
    ctx.db.conn.commit()
    return cid


def test_curl_returns_cache_hit(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import web
    url = "https://docs.example.com/page"
    _seed_cache(ctx, url)
    res = web.curl(ctx, "agent_x", {"url": url, "purpose": "docs"})
    assert res["status"] == "ok"
    assert res["cache_hit"] is True


def test_search_and_read_cache(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import web
    url = "https://docs.example.com/pathlib"
    cid = _seed_cache(ctx, url, body="pathlib resolves paths")
    s = web.search_web_cache(ctx, "agent_x", {"query": "pathlib"})
    assert s["count"] == 1 and s["results"][0]["cache_id"] == cid
    r = web.read_cached_page(ctx, "agent_x", {"cache_id": cid})
    assert r["status"] == "ok" and "resolves paths" in r["content"]


def test_curl_blocks_private(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import web
    res = web.curl(ctx, "agent_x", {"url": "https://127.0.0.1/secret", "purpose": "x"})
    assert res["status"] == "error" and res["failure"] == "web_fetch_failed"
