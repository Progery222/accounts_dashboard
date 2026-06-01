"""Test 3 YouTube Apify actors vs DB for phil.report."""
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

USERNAME = "phil.report"
CHANNEL_URL = f"https://www.youtube.com/@{USERNAME}"
ACCOUNT_ID = 196
MAX_VIDEOS = 50

ACTORS: list[tuple[str, str, dict]] = [
    (
        "streamers/youtube-channel-scraper",
        "streamers~youtube-channel-scraper",
        {
            "startUrls": [{"url": CHANNEL_URL}],
            "maxResults": MAX_VIDEOS,
            "maxResultsShorts": 0,
        },
    ),
    (
        "streamers/youtube-scraper",
        "streamers~youtube-scraper",
        {
            "startUrls": [{"url": CHANNEL_URL}],
            "maxResults": MAX_VIDEOS,
        },
    ),
    (
        "code-node-tools/youtube-scraper",
        "code-node-tools~youtube-scraper",
        {
            "inputType": "channel",
            "channelUrls": [CHANNEL_URL],
            "maxResults": MAX_VIDEOS,
            "sortBy": "newest",
        },
    ),
]


def apify_run(token: str, actor: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 180) -> tuple[str, list]:
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


def video_id_from_row(row: dict) -> str:
    for k in ("id", "videoId", "video_id"):
        v = str(row.get(k) or "").strip()
        if re.match(r"^[a-zA-Z0-9_-]{11}$", v):
            return v
    for k in ("url", "videoUrl", "link"):
        m = re.search(r"(?:v=|/shorts/|/embed/)([a-zA-Z0-9_-]{11})", str(row.get(k) or ""))
        if m:
            return m.group(1)
    return ""


def int_field(row: dict, *keys: str) -> int:
    for k in keys:
        v = row.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if v is not None and str(v).replace(",", "").strip().isdigit():
            return int(str(v).replace(",", "").strip())
    return 0


def posts_from_items(items: list) -> list[dict]:
    posts = []
    for row in items:
        vid = video_id_from_row(row)
        if not vid:
            continue
        posts.append(
            {
                "external_id": vid,
                "view_count": int_field(row, "viewCount", "views", "view_count"),
                "like_count": int_field(row, "likes", "likeCount", "likesCount", "like_count"),
                "title": (row.get("title") or row.get("name") or "")[:80],
            }
        )
    return posts


def profile_from_items(items: list) -> dict:
    for row in items:
        if row.get("channelName") or row.get("numberOfSubscribers") is not None:
            if video_id_from_row(row):
                continue
            return row
        if row.get("subscriberCount") is not None and not video_id_from_row(row):
            return row
    if items:
        r0 = items[0]
        return {
            "channelName": r0.get("channelName") or r0.get("channelUsername"),
            "numberOfSubscribers": r0.get("numberOfSubscribers") or r0.get("subscriberCount"),
            "channelTotalVideos": r0.get("channelTotalVideos") or r0.get("videoCount"),
        }
    return {}


def compare(apify_posts: list[dict], db_posts: dict) -> dict:
    ap = {p["external_id"]: p for p in apify_posts}
    db_ids = set(db_posts)
    ap_ids = set(ap)
    common = db_ids & ap_ids
    view_ok = view_diff = view_miss = 0
    like_ok = like_diff = 0
    for sc in common:
        dv = int(db_posts[sc].view_count or 0)
        av = ap[sc]["view_count"]
        dl = int(db_posts[sc].like_count or 0)
        al = ap[sc]["like_count"]
        if av == 0 and dv > 0:
            view_miss += 1
        elif dv == av or (dv and abs(dv - av) / max(dv, av) < 0.15):
            view_ok += 1
        else:
            view_diff += 1
        if dl == al:
            like_ok += 1
        else:
            like_diff += 1
    return {
        "db_n": len(db_ids),
        "apify_n": len(ap_ids),
        "common": len(common),
        "only_db": sorted(db_ids - ap_ids)[:15],
        "only_apify": sorted(ap_ids - db_ids)[:15],
        "view_ok": view_ok,
        "view_diff": view_diff,
        "view_miss": view_miss,
        "like_ok": like_ok,
        "like_diff": like_diff,
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

    print("=== DB (YouTube @phil.report) ===")
    print(
        f"id={acc.id} followers={acc.follower_count} post_count={acc.post_count} "
        f"posts_in_db={len(db_posts)} name={acc.display_name!r}"
    )

    out_dir = Path(__file__).resolve().parents[1] / "_apify_yt_out" / USERNAME
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
            subs = prof.get("numberOfSubscribers") or prof.get("subscriberCount")
            cmp = compare(posts, db_posts)
            summary[label] = {
                "run_id": run_id,
                "elapsed_sec": round(elapsed, 1),
                "items": len(items),
                "subscribers": subs,
                "posts_n": len(posts),
                "compare": {k: v for k, v in cmp.items() if k != "ap"},
            }
            print(f"  {elapsed:.1f}s items={len(items)} videos={len(posts)} subs={subs}")
            print(
                f"  overlap common={cmp['common']} db={cmp['db_n']} apify={cmp['apify_n']} "
                f"views OK={cmp['view_ok']} DIFF={cmp['view_diff']} miss={cmp['view_miss']}"
            )
            if cmp["only_db"]:
                print(f"  only_db: {cmp['only_db']}")
            if cmp["only_apify"]:
                print(f"  only_apify: {cmp['only_apify']}")
            ap_map = cmp["ap"]
            for sc in sorted(set(db_posts) & set(ap_map)):
                dv = int(db_posts[sc].view_count or 0)
                av = ap_map[sc]["view_count"]
                if dv != av:
                    print(f"    {sc} db_views={dv} apify_views={av}")
        except Exception as e:
            summary[label] = {"error": str(e)}
            print(f"  ERROR: {e}")

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out_dir}")


if __name__ == "__main__":
    main()
