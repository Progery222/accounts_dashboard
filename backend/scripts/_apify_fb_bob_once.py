"""One-off: Apify CrowdPull + playcount for one FB profile, compare with DB."""
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

PROFILE_URL = "https://www.facebook.com/profile.php?id=61588868450712"
FB_USERNAME = "61588868450712"
CROWD_ACTOR = "crowdpull~facebook-profile-scraper"
PLAYCOUNT_ACTOR = "social_developer~facebook-playcount-scraper"


def reel_id(url: str) -> str | None:
    u = str(url or "")
    if "/reel/" in u:
        return u.split("/reel/")[-1].strip("/").split("?")[0]
    return None


def apify_run(token: str, actor: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 120) -> list:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=180.0) as c:
        r = c.post(f"{base}/acts/{actor}/runs", json=inp, headers=headers)
        r.raise_for_status()
        data = r.json()["data"]
        run_id = data["id"]
        ds_id = data["defaultDatasetId"]
        print(f"[apify] {actor} run={run_id} dataset={ds_id}")
        for i in range(max_poll):
            time.sleep(poll_sec)
            st = c.get(f"{base}/actor-runs/{run_id}", headers=headers).json()["data"]
            status = st["status"]
            if i % 6 == 0 or status not in ("RUNNING", "READY"):
                print(f"  poll {i+1} {status}")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                if status != "SUCCEEDED":
                    print("  run meta:", json.dumps(st, ensure_ascii=False)[:800])
                break
        else:
            raise TimeoutError(f"run {run_id} still running after {max_poll * poll_sec}s")
        items = c.get(f"{base}/datasets/{ds_id}/items", headers=headers, params={"limit": 500}).json()
        return items if isinstance(items, list) else []


def main() -> None:
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token:
        print("Set APIFY_TOKEN in environment")
        sys.exit(1)

    import django

    django.setup()
    from accounts.models import Account, Platform, Post

    acc = Account.objects.filter(platform=Platform.FACEBOOK, username=FB_USERNAME).first()
    if not acc:
        print(f"No FB account username={FB_USERNAME!r} in DB")
        sys.exit(2)

    db_posts = {
        p.external_id: p
        for p in Post.objects.filter(account=acc).only(
            "external_id", "view_count", "like_count", "comment_count", "share_count", "posted_at"
        )
    }
    print("=== DB ===")
    print(
        f"account id={acc.id} {acc.display_name!r} followers={acc.follower_count} "
        f"likes={acc.like_count} view_sum={acc.view_count} posts={len(db_posts)}"
    )

    crowd_inp = {
        "startUrls": [{"url": PROFILE_URL}],
        "maxPosts": 80,
        "includeProfileInfo": True,
    }
    print("\n=== CrowdPull ===")
    crowd = apify_run(token, CROWD_ACTOR, crowd_inp)
    profile = next((x for x in crowd if x.get("type") == "profileInfo"), None)
    posts = [x for x in crowd if x.get("postId")]
    print(f"items={len(crowd)} profile={bool(profile)} posts={len(posts)}")
    if profile:
        print(f"  name={profile.get('name')!r} followersCount={profile.get('followersCount')}")

    reel_urls: list[str] = []
    crowd_by_reel: dict[str, dict] = {}
    for p in posts:
        u = str(p.get("postUrl") or "")
        rid = reel_id(u)
        if rid:
            reel_urls.append(u)
            crowd_by_reel[rid] = p

    apify_views: dict[str, int | None] = {}
    if reel_urls:
        print(f"\n=== Playcount ({len(reel_urls)} urls) ===")
        pc_inp = {
            "urlsText": "\n".join(reel_urls),
            "maxConcurrency": 8,
            "maxRetriesPerUrl": 3,
        }
        pc_items = apify_run(token, PLAYCOUNT_ACTOR, pc_inp, max_poll=80)
        for row in pc_items:
            vid = str(row.get("video_id") or reel_id(row.get("url") or "") or "")
            if not vid:
                continue
            pc = row.get("play_count")
            apify_views[vid] = int(pc) if pc is not None else None
            st = row.get("status")
            if st != "ok":
                print(f"  {vid} status={st}")

    print("\n=== Compare (reel id) ===")
    print(f"{'reel_id':<22} {'db_v':>8} {'apify_v':>8} {'db_l':>6} {'ap_r':>6} match")
    all_ids = sorted(set(db_posts) | set(crowd_by_reel) | set(apify_views))
    ok = close = miss = only_db = only_apify = 0
    for rid in all_ids:
        db = db_posts.get(rid)
        db_v = int(db.view_count) if db else None
        db_l = int(db.like_count) if db else None
        ap_v = apify_views.get(rid)
        cp = crowd_by_reel.get(rid)
        ap_r = int(cp.get("reactionCount") or 0) if cp else None
        if rid not in crowd_by_reel:
            only_db += 1
            tag = "only_db"
        elif rid not in db_posts:
            only_apify += 1
            tag = "only_apify"
        elif ap_v is None:
            miss += 1
            tag = "no_views"
        elif db_v is not None and abs(ap_v - db_v) <= max(2, int(db_v * 0.05)):
            ok += 1
            tag = "OK"
        elif db_v is not None and abs(ap_v - db_v) <= 10:
            close += 1
            tag = "~OK"
        else:
            tag = f"DIFF"
        print(f"{rid:<22} {str(db_v):>8} {str(ap_v):>8} {str(db_l):>6} {str(ap_r):>6} {tag}")

    print(
        f"\nSummary: db_posts={len(db_posts)} crowd_reels={len(crowd_by_reel)} "
        f"views_ok={ok} views_close={close} views_missing={miss} only_db={only_db} only_apify={only_apify}"
    )


if __name__ == "__main__":
    main()
