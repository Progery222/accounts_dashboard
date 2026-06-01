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

acc = Account.objects.get(platform=Platform.YOUTUBE, username="phil.report")
ids = [p.external_id for p in Post.objects.filter(account=acc)]
db = {p.external_id: int(p.view_count or 0) for p in Post.objects.filter(account=acc)}

urls = [{"url": f"https://www.youtube.com/watch?v={i}"} for i in ids]
token = os.environ["APIFY_TOKEN"]
h = {"Authorization": f"Bearer {token}"}
actor = "streamers~youtube-scraper"
inp = {"startUrls": urls}

rid = httpx.post(f"https://api.apify.com/v2/acts/{actor}/runs", json=inp, headers=h, timeout=60).json()["data"]["id"]
for _ in range(90):
    time.sleep(3)
    st = httpx.get(f"https://api.apify.com/v2/actor-runs/{rid}", headers=h).json()["data"]
    if st["status"] in ("SUCCEEDED", "FAILED"):
        break

ds = st["defaultDatasetId"]
items = httpx.get(f"https://api.apify.com/v2/datasets/{ds}/items", headers=h, params={"limit": 30}).json()
Path("_apify_yt_out/phil.report/by_urls.json").write_text(
    json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("status", st["status"], "items", len(items))
ok = diff = miss = 0
for row in items:
    vid = row.get("id")
    if not vid:
        continue
    av = int(row.get("viewCount") or 0)
    dv = db.get(vid, -1)
    if dv < 0:
        print("extra", vid, av)
        continue
    if av == 0 and dv > 0:
        miss += 1
        print(vid, "db", dv, "apify", av)
    elif dv == av:
        ok += 1
    else:
        diff += 1
        print(vid, "db", dv, "apify", av)
print(f"OK={ok} DIFF={diff} MISS={miss}")
