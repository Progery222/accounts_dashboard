"""Compare 3 Apify IG actors for one username vs dashboard field needs."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

USERNAME = "unfilteredphil1"
PROFILE_URL = f"https://www.instagram.com/{USERNAME}/"

ACTORS: list[tuple[str, str, dict]] = [
    (
        "apify/instagram-profile-scraper",
        "apify~instagram-profile-scraper",
        {"usernames": [USERNAME]},
    ),
    (
        "apify/instagram-scraper",
        "apify~instagram-scraper",
        {
            "directUrls": [PROFILE_URL],
            "resultsType": "posts",
            "resultsLimit": 30,
            "searchType": "user",
            "searchLimit": 1,
        },
    ),
    (
        "apify/instagram-reel-scraper",
        "apify~instagram-reel-scraper",
        {
            "directUrls": [f"https://www.instagram.com/{USERNAME}/reels/"],
            "resultsLimit": 30,
        },
    ),
]

NEEDS = [
    "display_name",
    "avatar_url",
    "bio",
    "follower_count",
    "following_count",
    "post_count",
    "posts.external_id (shortcode)",
    "posts.view_count",
    "posts.like_count",
    "posts.comment_count",
    "posts.thumbnail_url",
    "posts.post_url",
    "posts.posted_at",
]


def apify_run(token: str, actor_slug: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 90) -> tuple[str, list]:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=180.0) as c:
        r = c.post(f"{base}/acts/{actor_slug}/runs", json=inp, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"start failed {r.status_code}: {r.text[:500]}")
        data = r.json()["data"]
        run_id = data["id"]
        ds_id = data["defaultDatasetId"]
        for i in range(max_poll):
            time.sleep(poll_sec)
            st = c.get(f"{base}/actor-runs/{run_id}", headers=headers).json()["data"]
            status = st["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                if status != "SUCCEEDED":
                    raise RuntimeError(f"run {run_id} {status}: {json.dumps(st, ensure_ascii=False)[:600]}")
                break
        else:
            raise TimeoutError(run_id)
        items = c.get(f"{base}/datasets/{ds_id}/items", headers=headers, params={"limit": 500}).json()
        return run_id, items if isinstance(items, list) else []


def shortcode_from_url(url: str) -> str | None:
    m = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else None


def analyze_profile_scraper(items: list) -> dict:
    if not items:
        return {"error": "empty dataset"}
    row = items[0]
    latest = row.get("latestPosts") or row.get("latestIgtvVideos") or []
    posts = []
    for p in latest:
        sc = p.get("shortCode") or p.get("shortcode") or shortcode_from_url(p.get("url") or "")
        posts.append(
            {
                "external_id": sc,
                "view_count": p.get("videoViewCount") or p.get("videoPlayCount") or p.get("playCount") or 0,
                "like_count": p.get("likesCount") or p.get("likes") or 0,
                "comment_count": p.get("commentsCount") or p.get("comments") or 0,
                "thumbnail_url": bool(p.get("displayUrl") or p.get("thumbnailUrl")),
                "post_url": p.get("url") or "",
                "posted_at": p.get("timestamp") or p.get("takenAtTimestamp"),
            }
        )
    return {
        "display_name": row.get("fullName") or row.get("username"),
        "avatar_url": bool(row.get("profilePicUrl") or row.get("profilePicUrlHD")),
        "bio": bool(row.get("biography")),
        "follower_count": row.get("followersCount") or row.get("followers"),
        "following_count": row.get("followsCount") or row.get("following"),
        "post_count": row.get("postsCount") or row.get("posts"),
        "posts_n": len(posts),
        "posts_with_views": sum(1 for p in posts if int(p.get("view_count") or 0) > 0),
        "posts_with_likes": sum(1 for p in posts if int(p.get("like_count") or 0) > 0),
        "posts_with_shortcode": sum(1 for p in posts if p.get("external_id")),
        "sample_posts": posts[:3],
        "items_total": len(items),
    }


def analyze_instagram_scraper(items: list) -> dict:
    posts = []
    profile = {}
    for row in items:
        if row.get("error"):
            continue
        if row.get("username") and row.get("followersCount") is not None and not row.get("shortCode"):
            profile = row
        sc = row.get("shortCode") or row.get("shortcode") or shortcode_from_url(row.get("url") or "")
        if sc or row.get("type") in ("Video", "Image", "Sidecar", "Reel"):
            posts.append(
                {
                    "external_id": sc,
                    "view_count": row.get("videoViewCount") or row.get("videoPlayCount") or row.get("playCount") or 0,
                    "like_count": row.get("likesCount") or row.get("likes") or 0,
                    "comment_count": row.get("commentsCount") or row.get("comments") or 0,
                    "thumbnail_url": bool(row.get("displayUrl") or row.get("thumbnailUrl")),
                    "post_url": row.get("url") or "",
                    "posted_at": row.get("timestamp"),
                    "type": row.get("type"),
                }
            )
    return {
        "display_name": profile.get("fullName") or profile.get("ownerFullName"),
        "avatar_url": bool(profile.get("profilePicUrl")),
        "bio": bool(profile.get("biography")),
        "follower_count": profile.get("followersCount") or profile.get("followers"),
        "following_count": profile.get("followsCount"),
        "post_count": profile.get("postsCount"),
        "posts_n": len(posts),
        "posts_with_views": sum(1 for p in posts if int(p.get("view_count") or 0) > 0),
        "posts_with_likes": sum(1 for p in posts if int(p.get("like_count") or 0) > 0),
        "posts_with_shortcode": sum(1 for p in posts if p.get("external_id")),
        "sample_posts": posts[:3],
        "items_total": len(items),
        "profile_row_found": bool(profile),
    }


def analyze_reel_scraper(items: list) -> dict:
    posts = []
    for row in items:
        sc = row.get("shortCode") or row.get("id") or shortcode_from_url(row.get("url") or "")
        posts.append(
            {
                "external_id": sc,
                "view_count": row.get("videoPlayCount") or row.get("videoViewCount") or row.get("playCount") or 0,
                "like_count": row.get("likesCount") or row.get("likes") or 0,
                "comment_count": row.get("commentsCount") or 0,
                "thumbnail_url": bool(row.get("displayUrl") or row.get("thumbnailUrl")),
                "post_url": row.get("url") or "",
                "posted_at": row.get("timestamp"),
            }
        )
    owner = items[0].get("ownerUsername") if items else None
    return {
        "display_name": owner,
        "avatar_url": False,
        "bio": False,
        "follower_count": None,
        "following_count": None,
        "post_count": None,
        "posts_n": len(posts),
        "posts_with_views": sum(1 for p in posts if int(p.get("view_count") or 0) > 0),
        "posts_with_likes": sum(1 for p in posts if int(p.get("like_count") or 0) > 0),
        "posts_with_shortcode": sum(1 for p in posts if p.get("external_id")),
        "sample_posts": posts[:3],
        "items_total": len(items),
    }


ANALYZERS = {
    "apify/instagram-profile-scraper": analyze_profile_scraper,
    "apify/instagram-scraper": analyze_instagram_scraper,
    "apify/instagram-reel-scraper": analyze_reel_scraper,
}


def playwright_baseline() -> dict | None:
    worker = Path(__file__).resolve().parents[1] / "platforms" / "instagram" / "worker.py"
    if not worker.exists():
        return None
    import subprocess

    payload = json.dumps({"username": USERNAME})
    try:
        proc = subprocess.run(
            [sys.executable, str(worker), payload],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(worker.parent),
        )
    except subprocess.TimeoutExpired:
        return {"error": "playwright timeout 300s"}
    if proc.returncode != 0:
        return {"error": (proc.stderr or proc.stdout or "")[:400]}
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": f"parse: {e}", "raw": (proc.stdout or "")[:400]}
    posts = data.get("_posts") or []
    return {
        "display_name": data.get("display_name"),
        "follower_count": data.get("follower_count"),
        "following_count": data.get("following_count"),
        "post_count": data.get("post_count"),
        "posts_n": len(posts),
        "posts_with_views": sum(1 for p in posts if int(p.get("view_count") or 0) > 0),
        "posts_with_likes": sum(1 for p in posts if int(p.get("like_count") or 0) > 0),
        "sample_posts": [
            {
                "external_id": p.get("external_id"),
                "view_count": p.get("view_count"),
                "like_count": p.get("like_count"),
            }
            for p in posts[:3]
        ],
    }


def main() -> None:
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token:
        print("APIFY_TOKEN required")
        sys.exit(1)

    out_dir = Path(__file__).resolve().parents[1] / "_apify_ig_out"
    out_dir.mkdir(exist_ok=True)

    print("=== Playwright baseline (current worker) ===")
    pw = playwright_baseline()
    print(json.dumps(pw, ensure_ascii=False, indent=2))

    results: dict[str, dict] = {}
    for label, slug, inp in ACTORS:
        print(f"\n=== {label} ===")
        t0 = time.time()
        try:
            run_id, items = apify_run(token, slug, inp)
            elapsed = time.time() - t0
            (out_dir / f"{slug.replace('~', '_')}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            summary = ANALYZERS[label](items)
            summary["run_id"] = run_id
            summary["elapsed_sec"] = round(elapsed, 1)
            summary["first_item_keys"] = sorted(items[0].keys())[:25] if items else []
            results[label] = summary
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as e:
            results[label] = {"error": str(e)}
            print("ERROR:", e)

    (out_dir / "summary.json").write_text(json.dumps({"username": USERNAME, "pw": pw, "actors": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {out_dir}")


if __name__ == "__main__":
    main()
