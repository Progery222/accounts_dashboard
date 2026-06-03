#!/usr/bin/env python
"""Проверка сессии Instagram для Playwright (instagram_state.json + worker)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main() -> int:
    import django

    django.setup()

    from platforms.instagram.scraper import _call_instagram_worker
    from platforms.worker_utils import state_file_path

    state_path = state_file_path("instagram")
    print("=" * 60)
    print("Instagram Playwright session check")
    print("=" * 60)
    print(f"state file: {state_path}")
    print(f"exists: {state_path.exists()}")

    if not state_path.exists():
        print("FAIL: нет instagram_state.json — setup_instagram_auth --from-chrome или вход в настройках")
        return 1

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        ig = [c for c in cookies if "instagram.com" in (c.get("domain") or "")]
        names = {c.get("name") for c in ig}
        has_session = "sessionid" in names and any(
            c.get("name") == "sessionid" and c.get("value") for c in ig
        )
        print(f"instagram cookies: {len(ig)}, sessionid: {has_session}")
        if not has_session:
            print("FAIL: sessionid отсутствует в state")
            return 1
    except Exception as exc:
        print(f"FAIL: не прочитать state: {exc}")
        return 1

    test_user = (sys.argv[1] if len(sys.argv) > 1 else "freemarketsignal").lstrip("@")
    print(f"\nWorker counts_only @{test_user}…")
    try:
        counts = _call_instagram_worker({"username": test_user, "counts_only": True})
    except Exception as exc:
        print(f"FAIL worker: {exc}")
        return 1

    print(
        f"OK followers={counts.get('follower_count')} "
        f"following={counts.get('following_count')} posts={counts.get('post_count')}"
    )

    print(f"\nWorker scrape (dry) — полный профиль @{test_user}…")
    try:
        prof = _call_instagram_worker({"username": test_user})
    except Exception as exc:
        print(f"FAIL scrape: {exc}")
        return 1

    posts = prof.get("_posts") or []
    print(
        f"OK display_name={prof.get('display_name')!r} posts={len(posts)} "
        f"sample_views={[int(p.get('view_count') or 0) for p in posts[:3]]}"
    )
    print("\nПроверка пройдена.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
