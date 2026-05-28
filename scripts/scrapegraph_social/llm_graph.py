"""SmartScraperGraph с html_mode=True (без Html2Text ParseNode)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


def output_schema_model():
    class PostRow(BaseModel):
        external_id: str = ""
        post_url: str = ""
        view_count: int = 0
        like_count: int = 0

    class Extract(BaseModel):
        username: str = ""
        follower_count: int = 0
        post_count: int = 0
        posts: list[PostRow] = Field(default_factory=list)
        notes: str = ""

    return Extract


EXTRACT_PROMPT = """
You receive a JSON blob extracted from a social profile page (not raw HTML).
Use ONLY fields present in the JSON. Do not invent metrics.

Return:
- follower_count (int)
- post_count (int)
- posts: list of {external_id, post_url, view_count, like_count}
- notes: empty string if OK, else explain missing data / login wall

For YouTube: use embedded_video_ids to build watch URLs.
For Instagram: use embedded_shortcodes for reel/p URLs.
For Facebook: use embedded_facebook_reel_ids for reel URLs.
""".strip()


def build_graph_config(
    *,
    headless: bool,
    llm_provider: str,
    model: str,
    html_mode: bool = True,
) -> dict:
    if llm_provider == "openai":
        import os
        import sys

        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            print("Нужен OPENAI_API_KEY", file=sys.stderr)
            raise SystemExit(1)
        llm = {"api_key": api_key, "model": model or "openai/gpt-4o-mini"}
    else:
        llm = {
            "model": model or "ollama/llama3.2",
            "model_tokens": 8192,
            "format": "json",
        }

    return {
        "llm": llm,
        "verbose": True,
        "headless": headless,
        "html_mode": html_mode,
        "loader_kwargs": {"timeout": 120000},
    }


def run_on_context(
    context_json: str,
    *,
    headless: bool,
    llm_provider: str,
    model: str,
    html_mode: bool = True,
) -> dict[str, Any]:
    from scrapegraphai.graphs import SmartScraperGraph

    graph = SmartScraperGraph(
        prompt=EXTRACT_PROMPT,
        source=context_json,
        config=build_graph_config(
            headless=headless,
            llm_provider=llm_provider,
            model=model,
            html_mode=html_mode,
        ),
        schema=output_schema_model(),
    )
    raw = graph.run()
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw_text": raw, "notes": "LLM returned non-JSON"}
    return {"raw": raw, "notes": "unexpected LLM response type"}


def merge_deterministic_and_llm(det: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """Приоритет: детерминированные посты; LLM дополняет счётчики если пусто."""
    out = dict(det)
    out["_extraction"] = "hybrid"

    if int(llm.get("follower_count") or 0) > int(out.get("follower_count") or 0):
        out["follower_count"] = int(llm["follower_count"])
    if int(llm.get("post_count") or 0) > int(out.get("post_count") or 0):
        out["post_count"] = int(llm["post_count"])

    det_posts = {str(p.get("external_id")): p for p in (out.get("_posts") or []) if p.get("external_id")}
    for row in llm.get("posts") or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("external_id") or "").strip()
        if not eid:
            continue
        if eid not in det_posts:
            det_posts[eid] = {
                "external_id": eid,
                "post_url": str(row.get("post_url") or ""),
                "view_count": int(row.get("view_count") or 0),
                "like_count": int(row.get("like_count") or 0),
                "description": "",
                "thumbnail_url": "",
            }
        else:
            p = det_posts[eid]
            if int(row.get("view_count") or 0) > int(p.get("view_count") or 0):
                p["view_count"] = int(row["view_count"])
            if int(row.get("like_count") or 0) > int(p.get("like_count") or 0):
                p["like_count"] = int(row["like_count"])

    posts = list(det_posts.values())
    out["_posts"] = posts
    out["posts"] = [
        {
            "external_id": p["external_id"],
            "post_url": p["post_url"],
            "view_count": p["view_count"],
            "like_count": p["like_count"],
        }
        for p in posts
    ]
    out["post_count"] = max(int(out.get("post_count") or 0), len(posts))

    llm_notes = (llm.get("notes") or "").strip()
    if llm_notes and not (out.get("notes") or "").strip():
        out["notes"] = llm_notes

    return out
