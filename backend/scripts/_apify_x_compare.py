"""Test 3 X/Twitter Apify actors vs DB for greta_cities."""
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

USERNAME = "greta_cities"
ACCOUNT_ID = 106
MAX_ITEMS = 50

ACTORS: list[tuple[str, str, dict]] = [
    (
        "apidojo/twitter-scraper-lite",
        "apidojo~twitter-scraper-lite",
        {
            "twitterHandles": [USERNAME],
            "maxItems": MAX_ITEMS,
            "sort": "Latest",
        },
    ),
    (
        "apidojo/tweet-scraper",
        "apidojo~tweet-scraper",
        {
            "twitterHandles": [USERNAME],
            "maxItems": MAX_ITEMS,
        },
    ),
    (
        "scraper_one/x-profile-posts-scraper",
        "scraper_one~x-profile-posts-scraper",
        {
            "profileUrls": [f"https://x.com/{USERNAME}"],
            "maxPosts": MAX_ITEMS,
        },
    ),
]


def apify_run(token: str, actor: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 120) -> tuple[str, list]:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=180.0) as c:
        r = c.post(f"{base}/acts/{actor}/runs", json=inp, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"start {r.status_code}: {r.text[:700]}")
        data = r.json()["data"]
        run_id, ds_id = data["id"], data["defaultDatasetId"]
        for _ in range(max_poll):
            time.sleep(poll_sec)
            st = c.get(f"{base}/actor-runs/{run_id}", headers=headers).json()["data"]
            if st["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                if st["status"] != "SUCCEEDED":
                    raise RuntimeError(json.dumps(st, ensure_ascii=False)[:900])
                break
        else:
            raise TimeoutError(run_id)
        items = c.get(f"{base}/datasets/{ds_id}/items", headers=headers, params={"limit": 500}).json()
        return run_id, items if isinstance(items, list) else []


def tweet_id_from_row(row: dict) -> str:
    for k in ("id", "tweetId", "tweet_id", "postId", "post_id"):
        v = row.get(k)
        if v is not None and str(v).strip().isdigit():
            return str(v).strip()
    for k in ("url", "tweetUrl", "twitterUrl", "postUrl"):
        m = re.search(r"/status/(\d+)", str(row.get(k) or ""))
        if m:
            return m.group(1)
    return ""


def views_from_row(row: dict) -> int:
    for k in ("viewCount", "views", "view_count", "impressionCount", "stats", "public_metrics"):
        v = row.get(k)
        if isinstance(v, dict):
            for sk in ("view_count", "impression_count", "views"):
                if v.get(sk) is not None:
                    return int(v[sk])
        if isinstance(v, (int, float)):
            return int(v)
        if v is not None and str(v).replace(",", "").strip().isdigit():
            return int(str(v).replace(",", "").strip())
    return 0


def likes_from_row(row: dict) -> int:
    for k in ("likeCount", "likes", "favoriteCount", "like_count"):
        v = row.get(k)
        if isinstance(v, dict):
            return int(v.get("like_count") or v.get("favorite_count") or 0)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def profile_from_items(items: list) -> dict:
    prof = {}
    for row in items:
        if row.get("type") in ("profile", "user", "User") or (
            row.get("followers") is not None and not tweet_id_from_row(row)
        ):
            prof = row
    # apidojo often embeds author on first tweet
    if not prof and items:
        a = items[0].get("author") or items[0].get("user") or {}
        if isinstance(a, dict) and a.get("userName") or a.get("username"):
            prof = a
    return prof


def posts_from_items(items: list) -> list[dict]:
    posts = []
    for row in items:
        tid = tweet_id_from_row(row)
        if not tid:
            continue
        text = row.get("text") or row.get("fullText") or row.get("full_text") or ""
        if not text and row.get("type") in ("profile", "user"):
            continue
        posts.append(
            {
                "external_id": tid,
                "view_count": views_from_row(row),
                "like_count": likes_from_row(row),
                "description": (text or "")[:200],
            }
        )
    return posts


def profile_metrics(prof: dict, items: list) -> dict:
    if not prof and items:
        prof = profile_from_items(items)
    fc = prof.get("followers") or prof.get("followersCount") or prof.get("followers_count")
    if isinstance(fc, dict):
        fc = fc.get("count")
    pc = prof.get("statusesCount") or prof.get("statuses_count") or prof.get("postCount")
    name = prof.get("name") or prof.get("fullName") or prof.get("displayName")
    return {
        "followers": int(fc) if fc is not None and str(fc).replace(",", "").isdigit() else fc,
        "post_count": pc,
        "display_name": name,
    }


def compare(apify_posts: list[dict], db_posts: dict) -> dict:
    ap = {p["external_id"]: p for p in apify_posts}
    db_ids = set(db_posts)
    ap_ids = set(ap)
    common = db_ids & ap_ids
    view_ok = view_diff = view_miss = 0
    for sc in common:
        dv = int(db_posts[sc].view_count or 0)
        av = ap[sc]["view_count"]
        if av == 0 and dv > 0:
            view_miss += 1
        elif dv == av or (dv and abs(dv - av) / max(dv, av) < 0.12):
            view_ok += 1
        else:
            view_diff += 1
    return {
        "db_n": len(db_ids),
        "apify_n": len(ap_ids),
        "common": len(common),
        "only_db": sorted(db_ids - ap_ids),
        "only_apify": sorted(ap_ids - db_ids)[:12],
        "view_ok": view_ok,
        "view_diff": view_diff,
        "view_miss": view_miss,
        "ap": ap,
    }


def main() -> None:
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token:
        print("APIFY_TOKEN required")
        sys.exit(1)

    import django

    django.setup()
    from accounts.models import Account, Post

    acc = Account.objects.get(pk=ACCOUNT_ID)
    db_posts = {p.external_id: p for p in Post.objects.filter(account=acc)}

    print("=== DB (X @greta_cities) ===")
    print(
        f"id={acc.id} followers={acc.follower_count} post_count={acc.post_count} "
        f"posts_in_db={len(db_posts)} name={acc.display_name!r}"
    )
    for sc, p in db_posts.items():
        print(f"  {sc} views={p.view_count} likes={p.like_count}")

    out_dir = Path(__file__).resolve().parents[1] / "_apify_x_out" / USERNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}

    for label, slug, inp in ACTORS:
        print(f"\n=== {label} ===")
        t0 = time.time()
        try:
            run_id, items = apify_run(token, slug, inp)
            elapsed = time.time() - t0
            (out_dir / f"{slug.replace('~', '_')}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            prof = profile_from_items(items)
            posts = posts_from_items(items)
            pm = profile_metrics(prof, items)
            cmp = compare(posts, db_posts)
            summary[label] = {
                "run_id": run_id,
                "elapsed_sec": round(elapsed, 1),
                "items": len(items),
                "profile": pm,
                "posts_n": len(posts),
                "compare": {k: v for k, v in cmp.items() if k != "ap"},
                "sample_keys": sorted(items[0].keys())[:25] if items else [],
            }
            print(f"  {elapsed:.1f}s items={len(items)} posts={len(posts)} profile={pm}")
            print(
                f"  overlap common={cmp['common']} only_db={cmp['only_db']} "
                f"only_apify={cmp['only_apify'][:5]} views OK={cmp['view_ok']} DIFF={cmp['view_diff']}"
            )
            ap_map = cmp.get("ap") or {p["external_id"]: p for p in posts}
            for sc in sorted(set(db_posts) & set(ap_map)):
                dv = int(db_posts[sc].view_count or 0)
                av = ap_map[sc]["view_count"]
                if dv != av:
                    print(f"    {sc} db={dv} apify={av}")
        except Exception as e:
            summary[label] = {"error": str(e)}
            print(f"  ERROR: {e}")

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out_dir}")


if __name__ == "__main__":
    main()
