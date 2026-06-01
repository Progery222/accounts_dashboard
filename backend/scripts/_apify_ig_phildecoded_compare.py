"""Hybrid Apify IG (profile + posts) vs DB for phildecoded."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

USERNAME = "phildecoded"
PROFILE_ACTOR = "apify~instagram-profile-scraper"
POSTS_ACTOR = "apify~instagram-scraper"
POSTS_LIMIT = 80


def apify_run(token: str, actor: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 120) -> list:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=180.0) as c:
        r = c.post(f"{base}/acts/{actor}/runs", json=inp, headers=headers)
        r.raise_for_status()
        data = r.json()["data"]
        run_id, ds_id = data["id"], data["defaultDatasetId"]
        print(f"  run {run_id} ({actor})")
        for i in range(max_poll):
            time.sleep(poll_sec)
            st = c.get(f"{base}/actor-runs/{run_id}", headers=headers).json()["data"]
            if st["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                if st["status"] != "SUCCEEDED":
                    raise RuntimeError(json.dumps(st, ensure_ascii=False)[:800])
                break
        else:
            raise TimeoutError(run_id)
        items = c.get(f"{base}/datasets/{ds_id}/items", headers=headers, params={"limit": 500}).json()
        return items if isinstance(items, list) else []


def post_views(row: dict) -> int:
    return max(int(row.get("videoViewCount") or 0), int(row.get("videoPlayCount") or 0))


def normalize_posts(items: list) -> list[dict]:
    out = []
    for row in items:
        sc = row.get("shortCode") or ""
        if not sc:
            continue
        out.append(
            {
                "external_id": sc,
                "view_count": post_views(row),
                "like_count": int(row.get("likesCount") or 0),
                "comment_count": int(row.get("commentsCount") or 0),
                "posted_at": row.get("timestamp"),
                "post_url": row.get("url") or f"https://www.instagram.com/p/{sc}/",
            }
        )
    return out


def main() -> None:
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token:
        print("APIFY_TOKEN required")
        sys.exit(1)

    import django

    django.setup()
    from accounts.models import Account, Platform, Post

    acc = Account.objects.filter(platform=Platform.INSTAGRAM, username__iexact=USERNAME).first()
    if not acc:
        print(f"No IG account {USERNAME}")
        sys.exit(2)

    db_posts = {
        p.external_id: p
        for p in Post.objects.filter(account=acc).only(
            "external_id", "view_count", "like_count", "comment_count", "posted_at"
        )
    }

    print("=== DB ===")
    print(
        f"id={acc.id} name={acc.display_name!r} followers={acc.follower_count} "
        f"post_count={acc.post_count} posts={len(db_posts)}"
    )

    t0 = time.time()
    print("\n=== Apify profile-scraper ===")
    prof_items = apify_run(token, PROFILE_ACTOR, {"usernames": [USERNAME]})
    print(f"  items={len(prof_items)} elapsed={time.time()-t0:.1f}s")

    print("\n=== Apify instagram-scraper (posts) ===")
    t1 = time.time()
    post_items = apify_run(
        token,
        POSTS_ACTOR,
        {
            "directUrls": [f"https://www.instagram.com/{USERNAME}/"],
            "resultsType": "posts",
            "resultsLimit": POSTS_LIMIT,
        },
    )
    print(f"  items={len(post_items)} elapsed={time.time()-t1:.1f}s")

    prof = prof_items[0] if prof_items else {}
    latest = prof.get("latestPosts") or []
    apify_posts = normalize_posts(post_items)
    apify_by_id = {p["external_id"]: p for p in apify_posts}
    latest_by_id = {}
    for p in latest:
        sc = p.get("shortCode") or ""
        if sc:
            latest_by_id[sc] = {
                "view_count": max(int(p.get("videoViewCount") or 0), int(p.get("videoPlayCount") or 0)),
                "like_count": int(p.get("likesCount") or 0),
                "comment_count": int(p.get("commentsCount") or 0),
            }

    print("\n=== Profile metrics: Apify vs DB ===")
    rows = [
        ("followers", prof.get("followersCount"), acc.follower_count),
        ("following", prof.get("followsCount"), None),
        ("post_count", prof.get("postsCount"), acc.post_count),
        ("display_name", prof.get("fullName"), acc.display_name),
    ]
    for label, ap, db in rows:
        if db is None:
            print(f"  {label}: apify={ap!r} (not in Account model)")
            continue
        mark = "OK" if ap == db else "DIFF"
        print(f"  {label}: apify={ap!r} db={db!r} [{mark}]")

    print(f"\n  latestPosts in profile run: {len(latest)} (full posts run: {len(apify_posts)})")

    db_ids = set(db_posts)
    ap_ids = set(apify_by_id)
    only_db = db_ids - ap_ids
    only_ap = ap_ids - db_ids
    common = db_ids & ap_ids

    print("\n=== Posts overlap ===")
    print(f"  db={len(db_ids)} apify_full={len(ap_ids)} common={len(common)} only_db={len(only_db)} only_apify={len(only_ap)}")

    view_ok = view_diff = view_miss = 0
    like_ok = like_diff = 0
    for sc in sorted(common):
        dbp = db_posts[sc]
        ap = apify_by_id[sc]
        dv, av = int(dbp.view_count or 0), ap["view_count"]
        dl, al = int(dbp.like_count or 0), ap["like_count"]
        if av == 0 and dv > 0:
            view_miss += 1
        elif dv == av or (dv and abs(dv - av) / max(dv, av) < 0.08):
            view_ok += 1
        else:
            view_diff += 1
        if dl == al or (dl == 0 and al == 0):
            like_ok += 1
        else:
            like_diff += 1

    print(f"\n=== Views (common {len(common)}, max(vv,vp)) ===")
    print(f"  OK~match: {view_ok}  DIFF: {view_diff}  apify_zero_db>0: {view_miss}")

    print(f"\n=== Likes (common) ===")
    print(f"  OK: {like_ok}  DIFF: {like_diff}")

    if view_diff:
        print("\n  Top view DIFFs:")
        diffs = []
        for sc in common:
            dbp = db_posts[sc]
            av = apify_by_id[sc]["view_count"]
            dv = int(dbp.view_count or 0)
            if dv and av and dv != av:
                diffs.append((sc, dv, av, abs(dv - av)))
        for sc, dv, av, d in sorted(diffs, key=lambda x: -x[3])[:8]:
            pct = 100 * abs(dv - av) / max(dv, av, 1)
            print(f"    {sc} db={dv} apify={av} delta={d} ({pct:.0f}%)")

    if only_db:
        print(f"\n  only in DB ({len(only_db)}):", ", ".join(sorted(only_db)[:10]), "..." if len(only_db) > 10 else "")
    if only_ap:
        print(f"  only in Apify ({len(only_ap)}):", ", ".join(sorted(only_ap)[:10]), "..." if len(only_ap) > 10 else "")

    out = Path(__file__).resolve().parents[1] / "_apify_ig_out" / "phildecoded"
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(prof_items, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "posts.json").write_text(json.dumps(post_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
