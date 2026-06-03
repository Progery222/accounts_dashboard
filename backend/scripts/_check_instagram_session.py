"""Проверка Instagram: instaloader .session + Playwright instagram_state.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings


def main() -> int:
    user = (getattr(settings, "INSTAGRAM_USERNAME", "") or "").strip()
    session_file = (getattr(settings, "INSTAGRAM_SESSION_FILE", "") or "instagram.session").strip()
    sp = Path(session_file)
    if not sp.is_absolute():
        sp = Path(_BACKEND) / sp

    print("=" * 60)
    print("Instagram session check")
    print("=" * 60)
    print(f"INSTAGRAM_USERNAME: {user or '(не задан)'}")
    print(f"INSTAGRAM_PASSWORD: {'задан' if getattr(settings, 'INSTAGRAM_PASSWORD', '') else 'нет'}")
    print(f"INSTAGRAM_SESSION_FILE: {sp}")
    print(f"  exists: {sp.exists()}  size: {sp.stat().st_size if sp.exists() else 0} bytes")

    # Playwright state
    from platforms.worker_utils import state_file_path

    state_path = state_file_path("instagram")
    print(f"\nPlaywright state: {state_path}")
    print(f"  exists: {state_path.exists()}")
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") or []
            ig = [c for c in cookies if "instagram.com" in (c.get("domain") or "")]
            names = {c.get("name") for c in ig}
            has_session = "sessionid" in names and any(
                c.get("name") == "sessionid" and c.get("value") for c in ig
            )
            print(f"  cookies (instagram): {len(ig)}")
            print(f"  sessionid present: {has_session}")
            print(f"  key names: {', '.join(sorted(n for n in names if n)[:12])}...")
        except Exception as e:
            print(f"  read error: {e}")

    # Instaloader
    print("\n--- Instaloader session ---")
    try:
        import instaloader
    except ImportError:
        print("FAIL: instaloader не установлен (pip install instaloader)")
        return 1

    if not sp.exists():
        print("FAIL: файл сессии не найден")
        return 1

    if not user:
        print("SKIP: нет INSTAGRAM_USERNAME для проверки входа")
        return 1

    L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
    try:
        L.load_session_from_file(user, str(sp))
        print(f"OK: сессия загружена для @{user}")
    except Exception as e:
        print(f"FAIL: load_session_from_file: {e}")
        return 1

    test_targets = [user, "freemarketsignal"]
    for target in test_targets:
        print(f"\n  Profile.from_username(@{target}):")
        try:
            p = instaloader.Profile.from_username(L.context, target)
            print(
                f"    OK  full_name={p.full_name!r}  followers={p.followers}  "
                f"mediacount={p.mediacount}"
            )
            try:
                n = 0
                for post in p.get_posts():
                    n += 1
                    if n >= 3:
                        break
                print(f"    OK  get_posts: хотя бы {n} пост(ов) доступны")
            except Exception as pe:
                print(f"    WARN get_posts: {pe}")
        except Exception as e:
            print(f"    FAIL: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
