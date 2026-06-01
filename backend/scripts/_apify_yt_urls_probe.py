import json
import os
import time

import httpx

token = os.environ["APIFY_TOKEN"]
h = {"Authorization": f"Bearer {token}"}
actor = "streamers~youtube-channel-scraper"
urls = [
    "https://www.youtube.com/@phil.report/videos",
    "https://www.youtube.com/@phil.report",
]

for url in urls:
    inp = {
        "startUrls": [{"url": url}],
        "maxResults": 15,
        "maxResultsShorts": 0,
        "sortVideosBy": "NEWEST",
    }
    rid = httpx.post(f"https://api.apify.com/v2/acts/{actor}/runs", json=inp, headers=h).json()["data"]["id"]
    for _ in range(50):
        time.sleep(3)
        st = httpx.get(f"https://api.apify.com/v2/actor-runs/{rid}", headers=h).json()["data"]
        if st["status"] in ("SUCCEEDED", "FAILED"):
            break
    ds = st["defaultDatasetId"]
    items = httpx.get(f"https://api.apify.com/v2/datasets/{ds}/items", headers=h, params={"limit": 3}).json()
    print(url, st["status"], len(items), json.dumps(items[0] if items else {}, ensure_ascii=False)[:200])
