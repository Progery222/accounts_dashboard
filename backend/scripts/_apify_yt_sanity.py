"""Sanity check streamers YT actor + DB vs YouTube API."""
import json
import os
import time

import httpx

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def run_actor(url: str, max_results: int = 10) -> list:
    token = os.environ["APIFY_TOKEN"]
    h = {"Authorization": f"Bearer {token}"}
    actor = "streamers~youtube-channel-scraper"
    inp = {
        "startUrls": [{"url": url}],
        "maxResults": max_results,
        "maxResultsShorts": 0,
        "sortVideosBy": "NEWEST",
    }
    rid = httpx.post(f"https://api.apify.com/v2/acts/{actor}/runs", json=inp, headers=h, timeout=60).json()["data"]["id"]
    for _ in range(80):
        time.sleep(3)
        st = httpx.get(f"https://api.apify.com/v2/actor-runs/{rid}", headers=h).json()["data"]
        if st["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
    ds_id = st["defaultDatasetId"]
    return httpx.get(f"https://api.apify.com/v2/datasets/{ds_id}/items", headers=h, params={"limit": 50}).json()


def main() -> None:
    for label, url in (
        ("apify_channel", "https://www.youtube.com/@Apify"),
        ("phil_report", "https://www.youtube.com/@phil.report"),
    ):
        items = run_actor(url)
        print(f"\n=== {label} === items={len(items)}")
        if items:
            print(json.dumps(items[0], ensure_ascii=False)[:300])
        vids = [i.get("id") for i in items if i.get("id")]
        print("video ids:", len(vids), vids[:3])

    import django

    django.setup()
    from accounts.models import Account, Platform, Post
    from platforms.youtube.scraper import fetch_youtube_channel

    acc = Account.objects.get(platform=Platform.YOUTUBE, username="phil.report")
    db = {p.external_id: p for p in Post.objects.filter(account=acc)}
    api = fetch_youtube_channel("phil.report")
    ap = {p["external_id"]: p for p in api.get("_posts", [])}
    print("\n=== DB vs YouTube API ===")
    print(f"followers db={acc.follower_count} api={api.get('follower_count')}")
    print(f"posts db={len(db)} api={len(ap)} common={len(set(db) & set(ap))}")
    for sc in sorted(set(db) & set(ap))[:8]:
        dv, av = int(db[sc].view_count or 0), int(ap[sc].view_count or 0)
        if dv != av:
            print(f"  {sc} views db={dv} api={av}")


if __name__ == "__main__":
    main()
