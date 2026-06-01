import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from accounts.models import Account, Platform, Post

token = os.environ["APIFY_TOKEN"]
h = {"Authorization": f"Bearer {token}"}
CHANNEL = "https://www.youtube.com/@phil.report"

tests = [
    ("youtube-scraper-channel", "streamers~youtube-scraper", {"startUrls": [{"url": CHANNEL}], "maxResults": 30}),
    ("youtube-channel-scraper", "streamers~youtube-channel-scraper", {
        "startUrls": [{"url": CHANNEL}],
        "maxResults": 30,
        "maxResultsShorts": 0,
        "sortVideosBy": "NEWEST",
    }),
]

acc = Account.objects.get(platform=Platform.YOUTUBE, username="phil.report")
db = {p.external_id: int(p.view_count or 0) for p in Post.objects.filter(account=acc)}

for name, actor, inp in tests:
    rid = httpx.post(f"https://api.apify.com/v2/acts/{actor}/runs", json=inp, headers=h, timeout=60).json()["data"]["id"]
    for _ in range(90):
        time.sleep(3)
        st = httpx.get(f"https://api.apify.com/v2/actor-runs/{rid}", headers=h).json()["data"]
        if st["status"] in ("SUCCEEDED", "FAILED"):
            break
    items = httpx.get(
        f"https://api.apify.com/v2/datasets/{st['defaultDatasetId']}/items",
        headers=h,
        params={"limit": 50},
    ).json()
    vids = [i.get("id") for i in items if i.get("id")]
    print(name, st["status"], "items", len(items), "vids", len(vids), "err", items[0].get("error") if items else None)
    if items and items[0].get("numberOfSubscribers") is not None:
        print("  subs", items[0].get("numberOfSubscribers"))
