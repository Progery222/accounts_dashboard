#!/usr/bin/env python
"""
Smoke-test refresh Instagram (Playwright only).

  cd backend
  py -3.13 -m poetry run python scripts/refresh_instagram_trace.py freemarketsignal
  py -3.13 -m poetry run python scripts/refresh_instagram_trace.py freemarketsignal --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main() -> int:
    import django

    django.setup()

    from accounts.models import Account, Platform
    from platforms.instagram.scraper import fetch_instagram_profile

    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?", default="freemarketsignal")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    uname = args.username.lstrip("@")
    print(f"fetch_instagram_profile(@{uname}) …")
    payload = fetch_instagram_profile(uname)
    posts = payload.get("_posts") or []
    print(
        f"OK posts={len(posts)} followers={payload.get('follower_count')} "
        f"views_sum={sum(int(p.get('view_count') or 0) for p in posts)} "
        f"authoritative={payload.get('_posts_authoritative')}"
    )

    if args.apply:
        acc = Account.objects.filter(username__iexact=uname, platform=Platform.INSTAGRAM).first()
        if not acc:
            print("account not found in DB")
            return 1
        from accounts.views import _apply_refresh

        _apply_refresh(acc, scraped=payload)
        acc.refresh_from_db()
        print(f"applied account_id={acc.id} updated_at={acc.updated_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
