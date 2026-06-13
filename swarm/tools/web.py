"""Web tools (spec section 24): curl, search_web_cache, read_cached_page.

All routed through ctx.web_cache, which applies the web guard and caching.
"""
from __future__ import annotations


def curl(ctx, agent_id: str, args: dict) -> dict:
    if not ctx.settings.get_bool("WEB_ACCESS_ENABLED", True):
        return {"status": "error", "failure": "permission_denied", "detail": "web disabled"}
    url = args.get("url", "")
    if not url:
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'url'"}
    reuse = args.get("cache_policy", "reuse_if_fresh") != "always_fetch"
    if not ctx.settings.get_bool("WEB_REUSE_CACHE_BY_DEFAULT", True):
        reuse = args.get("cache_policy") == "reuse_if_fresh"
    return ctx.web_cache.fetch(
        url=url, purpose=args.get("purpose", ""), agent_id=agent_id,
        max_age_hours=args.get("max_age_hours"), reuse=reuse,
    )


def search_web_cache(ctx, agent_id: str, args: dict) -> dict:
    results = ctx.web_cache.search(args.get("query", ""))
    return {"status": "ok", "results": results, "count": len(results)}


def read_cached_page(ctx, agent_id: str, args: dict) -> dict:
    cache_id = args.get("cache_id", "")
    if not cache_id:
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'cache_id'"}
    return ctx.web_cache.read(cache_id, int(args.get("max_chars", 20000)))
