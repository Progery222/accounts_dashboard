#!/usr/bin/env python
"""
Диагностический refresh Instagram: по шагам Instaloader, public httpx, Playwright /reels/,
merge как в production, отчёт «кто отдал какое поле». Опционально запись в БД.

  cd backend
  py -3.13 -m poetry run python scripts/refresh_instagram_trace.py freemarketsignal
  py -3.13 -m poetry run python scripts/refresh_instagram_trace.py freemarketsignal --apply
  py -3.13 -m poetry run python scripts/refresh_instagram_trace.py freemarketsignal --scrape-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def _setup_django() -> None:
    import django

    django.setup()


def _pw_reels_grid(username: str) -> tuple[list[dict], dict | None, str | None]:
    from platforms.instagram.scraper import _call_instagram_worker

    try:
        data = _call_instagram_worker({"username": username.lstrip("@"), "reels_views_only": True})
    except Exception as exc:
        return [], None, str(exc)

    grid = data.get("_reels_grid")
    if not grid:
        raw = data.get("_reels_views") or {}
        grid = [
            {
                "external_id": str(k),
                "view_count": int(v),
                "thumbnail_url": "",
                "description": "",
                "like_count": 0,
            }
            for k, v in raw.items()
        ]
    return list(grid or []), data, None


def _merge_with_attribution(posts_il: list[dict], grid: list[dict]) -> tuple[list[dict], list[dict]]:
    """Как _merge_posts_with_reels_grid_scraper + посты только из reels."""
    posts = [dict(p) for p in posts_il]
    by_grid = {r["external_id"]: r for r in grid if r.get("external_id")}
    timeline_ids = {p.get("external_id") for p in posts if p.get("external_id")}
    rows: list[dict] = []

    for p in posts:
        sid = p.get("external_id")
        il_v = int(p.get("view_count") or 0)
        pw_v = int(by_grid[sid].get("view_count") or 0) if sid and sid in by_grid else 0
        final_v = max(il_v, pw_v)
        view_src = "instaloader"
        if pw_v > il_v:
            view_src = "playwright_reels"
        elif pw_v > 0 and il_v == pw_v:
            view_src = "instaloader+playwright_reels (equal)"
        elif il_v == 0 and pw_v == 0:
            view_src = "none"

        row = {
            "external_id": sid,
            "view_count": final_v,
            "like_count": int(p.get("like_count") or 0),
            "comment_count": int(p.get("comment_count") or 0),
            "description": (p.get("description") or "")[:80],
            "posted_at": p.get("posted_at"),
            "_attribution": {
                "origin": "instaloader_timeline",
                "view_count": {"instaloader": il_v, "playwright_reels": pw_v, "final": final_v, "winner": view_src},
                "like_count": {"instaloader": int(p.get("like_count") or 0), "playwright_reels": None, "final": int(p.get("like_count") or 0), "winner": "instaloader"},
                "comment_count": {"instaloader": int(p.get("comment_count") or 0), "winner": "instaloader"},
                "description": {"instaloader": bool(p.get("description")), "winner": "instaloader"},
                "thumbnail_url": {"instaloader": bool(p.get("thumbnail_url")), "winner": "instaloader"},
                "posted_at": {"instaloader": bool(p.get("posted_at")), "winner": "instaloader"},
            },
        }
        rows.append(row)

    for r in grid:
        sc = r.get("external_id")
        if not sc or sc in timeline_ids:
            continue
        rows.append(
            {
                "external_id": sc,
                "view_count": int(r.get("view_count") or 0),
                "like_count": int(r.get("like_count") or 0),
                "comment_count": 0,
                "description": (r.get("description") or "")[:80],
                "posted_at": None,
                "_attribution": {
                    "origin": "playwright_reels_only",
                    "view_count": {
                        "instaloader": None,
                        "playwright_reels": int(r.get("view_count") or 0),
                        "final": int(r.get("view_count") or 0),
                        "winner": "playwright_reels",
                    },
                    "like_count": {
                        "instaloader": None,
                        "playwright_reels": int(r.get("like_count") or 0),
                        "final": int(r.get("like_count") or 0),
                        "winner": "playwright_reels",
                    },
                },
            }
        )

    merged_posts = []
    for p in posts:
        sid = p.get("external_id")
        if sid and sid in by_grid:
            g = by_grid[sid]
            tv = int(p.get("view_count") or 0)
            gv = int(g.get("view_count") or 0)
            p = dict(p)
            p["view_count"] = max(tv, gv)
        merged_posts.append(p)
    for r in grid:
        sc = r.get("external_id")
        if not sc or sc in timeline_ids:
            continue
        merged_posts.append(
            {
                "external_id": sc,
                "description": (r.get("description") or "")[:500],
                "thumbnail_url": r.get("thumbnail_url") or "",
                "post_url": f"https://www.instagram.com/reel/{sc}/",
                "view_count": int(r.get("view_count") or 0),
                "like_count": int(r.get("like_count") or 0),
                "comment_count": 0,
                "share_count": 0,
                "posted_at": None,
            }
        )
    return merged_posts, rows


def _profile_attribution(summary_il: dict, public: dict, final_summary: dict) -> dict:
    fields = ("display_name", "avatar_url", "bio", "follower_count", "following_count", "post_count")
    out = {}
    for f in fields:
        il_v = summary_il.get(f)
        pub_v = public.get(f) if f in ("follower_count", "following_count", "post_count") else None
        fin_v = final_summary.get(f)
        winner = "instaloader"
        note = ""
        if il_summary.get("_playwright_full"):
            winner = "playwright_full_profile"
        if f in ("follower_count", "following_count", "post_count") and pub_v and int(pub_v or 0) > 0:
            if int(il_v or 0) != int(pub_v):
                winner = "httpx_public_meta" if int(fin_v or 0) == int(pub_v) else "instaloader+httpx_public_meta"
                note = f"public_meta={pub_v}, instaloader={il_v}"
        if f in ("bio", "display_name", "avatar_url"):
            winner = "instaloader"
        out[f] = {
            "instaloader": il_v,
            "httpx_public_meta": pub_v,
            "playwright_full_profile": None,
            "final": fin_v,
            "winner": winner,
            "note": note,
        }
    return out


def run_trace(username: str, *, apply_db: bool) -> int:
    _setup_django()

    from accounts.models import Account, Platform, ScrapeBackendConfig
    from platforms.apify.config import use_apify_for_platform
    from platforms.instagram.posts_meta import annotate_instagram_posts_payload
    from platforms.instagram.scraper import (
        _fetch_public_meta_counts,
        _instagram_creds_from_settings,
        _instaloader_login_once,
        _instaloader_profile_and_posts_raw,
        _merge_reels_views_into_posts,
        fetch_instagram_profile,
    )

    uname = username.lstrip("@").strip().lower()
    display_uname = username.lstrip("@").strip()

    account = Account.objects.filter(username__iexact=uname, platform=Platform.INSTAGRAM).first()
    cfg = ScrapeBackendConfig.get()
    insta_user, insta_pass, session_file = _instagram_creds_from_settings()

    print("=" * 72)
    print(f"Instagram trace @{display_uname}")
    print("=" * 72)
    print(f"account_id: {account.id if account else '—'}")
    print(f"scrape_backend config: {cfg.instagram_backend}")
    print(f"use_apify_for_platform: {use_apify_for_platform(Platform.INSTAGRAM)}")
    print(f"instaloader creds: user={'yes' if insta_user else 'no'}, session_file={session_file or '—'}")
    print(f"full Playwright profile would run only if: no creds | FORCE_PW | empty IL profile")
    print()

    if use_apify_for_platform(Platform.INSTAGRAM):
        print("ERROR: instagram_backend=apify — этот скрипт для Playwright/Instaloader пути.")
        return 1

    # ── 1. Instaloader ─────────────────────────────────────────────────────
    print("[1/4] Instaloader (GraphQL + session)…")
    if not (insta_user and insta_pass):
        print("  SKIP: нет INSTAGRAM_USERNAME/PASSWORD")
        return 1

    il_error: str | None = None
    il_summary: dict = {}
    posts_il: list[dict] = []
    path_note = "instaloader_timeline"
    try:
        import instaloader  # noqa: F401

        L = _instaloader_login_once(insta_user, insta_pass, session_file)
        chunk = _instaloader_profile_and_posts_raw(L, display_uname)
        if isinstance(chunk, dict):
            print("  Instaloader вернул готовый dict (fallback/html/playwright) — см. production fetch.")
            il_summary = {k: v for k, v in chunk.items() if k != "_posts"}
            posts_il = list(chunk.get("_posts") or [])
            path_note = "mixed_or_playwright_fallback"
        else:
            il_summary, posts_il = chunk
    except ModuleNotFoundError:
        il_error = "instaloader не установлен: poetry run pip install instaloader"
        print(f"  ERROR: {il_error}")
    except Exception as exc:
        il_error = str(exc).replace("\n", " ")[:500]
        print(f"  ERROR (частичный сбой IL): {il_error}")
        # Попытка хотя бы summary без avatar_url (частый 400 на profile_pic)
        try:
            import instaloader as IL

            L2 = _instaloader_login_once(insta_user, insta_pass, session_file)
            prof = IL.Profile.from_username(L2.context, display_uname)
            il_summary = {
                "display_name": prof.full_name or display_uname,
                "avatar_url": None,
                "bio": prof.biography or "",
                "follower_count": prof.followers,
                "following_count": prof.followees,
                "like_count": 0,
                "post_count": prof.mediacount,
            }
            print(f"  partial IL summary OK: followers={il_summary.get('follower_count')}")
        except Exception as exc2:
            print(f"  partial IL also failed: {exc2}")

    print(f"  posts from instaloader: {len(posts_il)}")
    print(f"  summary: followers={il_summary.get('follower_count')} posts={il_summary.get('post_count')}")
    print()

    # ── 2. Public httpx meta ─────────────────────────────────────────────────
    print("[2/4] httpx public meta (без браузера)…")
    public = _fetch_public_meta_counts(display_uname)
    print(f"  public meta: {public}")
    print()

    # ── 3. Playwright reels only ─────────────────────────────────────────────
    print("[3/4] Playwright worker reels_views_only (/reels/)…")
    grid, pw_raw, pw_err = _pw_reels_grid(display_uname)
    if pw_err:
        print(f"  ERROR: {pw_err}")
    else:
        print(f"  reels grid rows: {len(grid)}")
        if pw_raw:
            print(f"  worker keys: {list(pw_raw.keys())}")
    print()

    # ── 4. Merge + production fetch ──────────────────────────────────────────
    print("[4/4] Merge (как в _fetch_instagram_instaloader) + fetch_instagram_profile…")
    final_summary = dict(il_summary)
    posts_before_pw = [dict(p) for p in posts_il]
    merged_manual, post_attrib = _merge_with_attribution(posts_il, grid)

    for key in ("follower_count", "following_count", "post_count"):
        pub_v = int(public.get(key) or 0)
        if pub_v > 0:
            final_summary[key] = pub_v

    production_note = "instaloader+playwright_reels (manual merge)"
    if not posts_il and grid:
        print("  Instaloader без постов -> production fetch_instagram_profile() (может уйти в full Playwright)…")
        payload_prod = fetch_instagram_profile(display_uname)
        production_note = "fetch_instagram_profile() production"
        if il_error and len(payload_prod.get("_posts") or []) > 0:
            production_note += " (Playwright full fallback — пустой/сломанный IL)"
            il_summary["_playwright_full"] = True
        by_grid = {r["external_id"]: r for r in grid if r.get("external_id")}
        post_attrib = []
        for p in payload_prod.get("_posts") or []:
            sid = p.get("external_id")
            gv = int(by_grid.get(sid, {}).get("view_count") or 0) if sid else 0
            fv = int(p.get("view_count") or 0)
            post_attrib.append(
                {
                    "external_id": sid,
                    "view_count": fv,
                    "like_count": int(p.get("like_count") or 0),
                    "_attribution": {
                        "origin": "production_fetch_instagram_profile",
                        "view_count": {
                            "instaloader": None,
                            "playwright_reels": gv,
                            "final": fv,
                            "winner": "playwright_full_or_reels" if gv < fv else "playwright_reels",
                        },
                        "like_count": {"instaloader": None, "winner": "playwright_timeline_or_il"},
                    },
                }
            )
    else:
        final_summary["_posts"] = merged_manual
        payload_prod = annotate_instagram_posts_payload(
            dict(final_summary, _posts=_merge_reels_views_into_posts(display_uname, posts_before_pw)),
        )

    prof_attr = _profile_attribution(
        il_summary or {},
        public,
        {k: v for k, v in payload_prod.items() if k != "_posts"},
    )

    print()
    print("=" * 72)
    print("ПРОФИЛЬ: источник полей (final = уйдёт в _apply_refresh)")
    print("=" * 72)
    for field, meta in prof_attr.items():
        print(f"  {field}:")
        print(f"    instaloader     = {meta['instaloader']!r}")
        if meta.get("httpx_public_meta") is not None:
            print(f"    httpx_public    = {meta['httpx_public_meta']!r}")
        print(f"    playwright full = {meta['playwright_full_profile']!r}")
        print(f"    FINAL           = {meta['final']!r}  <- {meta['winner']}")
        if meta.get("note"):
            print(f"    ({meta['note']})")

    print()
    print("=" * 72)
    print(f"ПОСТЫ: {len(post_attrib)} (показаны до {min(12, len(post_attrib))})")
    print("=" * 72)
    pw_wins = sum(1 for r in post_attrib if r["_attribution"]["view_count"]["winner"] == "playwright_reels")
    il_only_reels = sum(1 for r in post_attrib if r["_attribution"].get("origin") == "playwright_reels_only")
    print(f"  timeline from instaloader: {len(posts_il)}")
    print(f"  только из Playwright reels (нет в IL): {il_only_reels}")
    print(f"  просмотры: Playwright > Instaloader у {pw_wins} постов")
    print()

    for row in post_attrib[:12]:
        a = row["_attribution"]
        v = a["view_count"]
        print(f"  {row['external_id']}: views IL={v['instaloader']} PW={v['playwright_reels']} → {v['final']} ({v['winner']})")
        print(f"    likes IL={a['like_count']['instaloader']} → {row['like_count']} ({a['like_count']['winner']})")
        if a.get("origin") == "playwright_reels_only":
            print("    [пост добавлен только с /reels/]")

    if len(post_attrib) > 12:
        print(f"  … ещё {len(post_attrib) - 12} постов")

    totals_il_v = sum(int(p.get("view_count") or 0) for p in posts_il)
    totals_pw_v = sum(int(r.get("view_count") or 0) for r in grid)
    totals_fin_v = sum(int(p.get("view_count") or 0) for p in payload_prod.get("_posts") or [])
    totals_il_l = sum(int(p.get("like_count") or 0) for p in posts_il)
    totals_fin_l = sum(int(p.get("like_count") or 0) for p in payload_prod.get("_posts") or [])

    print()
    print("ИТОГО по постам:")
    print(f"  sum view_count  instaloader={totals_il_v}  playwright_grid={totals_pw_v}  final={totals_fin_v}")
    print(f"  sum like_count  instaloader={totals_il_l}  final={totals_fin_l}  (playwright reels не обновляет лайки)")
    print(f"  _posts_authoritative={payload_prod.get('_posts_authoritative')}  _partial={payload_prod.get('_partial')}")
    print(f"  production path: {production_note}")
    print()

    report_path = _BACKEND / "scripts" / f"_trace_{uname}_instagram.json"
    report = {
        "username": display_uname,
        "instaloader_error": il_error,
        "path_note": path_note,
        "profile": prof_attr,
        "posts_sample": post_attrib[:30],
        "totals": {
            "views_instaloader": totals_il_v,
            "views_playwright_grid": totals_pw_v,
            "views_final": totals_fin_v,
            "likes_instaloader": totals_il_l,
            "likes_final": totals_fin_l,
        },
        "production_payload_keys": list(payload_prod.keys()),
        "production_note": production_note,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"JSON отчёт: {report_path}")

    if apply_db:
        if not account:
            print("ERROR: аккаунт не найден в БД — refresh не применён.")
            return 1
        from accounts.views import _apply_refresh

        print()
        print("Применяю _apply_refresh в БД…")
        refreshed = _apply_refresh(account, scraped=payload_prod)
        print(
            f"OK account_id={refreshed.id} followers={refreshed.follower_count} "
            f"views={refreshed.view_count} likes={refreshed.like_count} posts={refreshed.post_count} "
            f"updated_at={refreshed.updated_at}"
        )
    else:
        print()
        print("БД не трогали (добавьте --apply для записи).")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace Instagram refresh by data source")
    parser.add_argument("username", nargs="?", default="freemarketsignal")
    parser.add_argument("--apply", action="store_true", help="Записать результат в БД через _apply_refresh")
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Только отчёт, без --apply (то же что по умолчанию)",
    )
    args = parser.parse_args()
    apply_db = args.apply and not args.scrape_only
    raise SystemExit(run_trace(args.username, apply_db=apply_db))


if __name__ == "__main__":
    main()
