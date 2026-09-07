"""Быстрый HTTP-first съём Rumble (curl_cffi) до challenge-solver / браузера."""
from __future__ import annotations

import os
import sys

from platforms.http_client import HttpClient
from platforms.rumble.parse import (
    about_urls,
    extract_posts,
    feed_urls,
    is_antibot_html,
    is_not_found_html,
    profile_from_html,
)


def http_direct_enabled() -> bool:
    raw = (os.environ.get("RUMBLE_HTTP_DIRECT") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def fetch_profile_http(username: str) -> dict:
    about_html = ""
    feed_html = ""
    best_feed_posts = 0

    with HttpClient(
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
        timeout=25.0,
    ) as client:
        print(f"[rumble] HTTP-direct ({client.backend}) для @{username}", file=sys.stderr)
        for url in feed_urls(username):
            try:
                r = client.get(url)
            except Exception as exc:
                print(f"[rumble] HTTP feed {url}: {exc}", file=sys.stderr)
                continue
            if r.status_code == 404 or is_not_found_html(r.text):
                continue
            if r.status_code >= 400 or is_antibot_html(r.text):
                print(
                    f"[rumble] HTTP feed blocked status={r.status_code} antibot={is_antibot_html(r.text)}",
                    file=sys.stderr,
                )
                continue
            posts_n = len(extract_posts(r.text))
            if posts_n > best_feed_posts or not feed_html:
                feed_html = r.text
                best_feed_posts = posts_n
            if posts_n > 0:
                break

        for url in about_urls(username):
            try:
                r = client.get(url)
            except Exception as exc:
                print(f"[rumble] HTTP about {url}: {exc}", file=sys.stderr)
                continue
            if r.status_code == 404 or is_not_found_html(r.text):
                continue
            if r.status_code >= 400 or is_antibot_html(r.text):
                continue
            about_html = r.text
            break

    if not about_html and not feed_html:
        raise RuntimeError(f"Rumble @{username}: HTTP-direct не прошёл (CF/пусто)")

    payload = profile_from_html(
        username=username,
        about_html=about_html,
        feed_html=feed_html,
    )
    payload["_source"] = "http_direct"
    posts = payload.get("_posts") or []
    post_count = int(payload.get("post_count") or 0)
    partial_posts = bool(post_count) and len(posts) < post_count
    payload["_quality_flags"] = {
        "anti_bot_detected": False,
        "about_parsed": bool(about_html),
        "feed_parsed": bool(feed_html),
        "partial_posts": partial_posts,
        "http_direct": True,
    }
    if not posts and post_count > 0:
        payload["_posts_authoritative"] = False
    elif partial_posts:
        payload["_posts_authoritative"] = False
    return payload
