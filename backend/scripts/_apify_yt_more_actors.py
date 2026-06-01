import json
import os
import re
import time
from pathlib import Path

import httpx

CHANNEL = "https://www.youtube.com/@phil.report"
token = os.environ["APIFY_TOKEN"]
h = {"Authorization": f"Bearer {token}"}

ACTORS = [
    ("streamers-channel", "streamers~youtube-channel-scraper", {"startUrls": [{"url": CHANNEL}], "maxResults": 30, "maxResultsShorts": 0, "sortVideosBy": "NEWEST"}),
    ("streamers-yt", "streamers~youtube-scraper", {"startUrls": [{"url": CHANNEL}], "maxResults": 30}),
    ("vortex", "vortex_data~youtube-scraper", {"startUrls": [{"url": CHANNEL}], "maxItems": 30}),
    ("grow_media", "grow_media~youtube-channel-scraper", {"channelUrls": [CHANNEL], "maxResults": 30}),
    ("epctex", "epctex~youtube-channel-scraper", {"startUrls": [CHANNEL], "maxResults": 30}),
]

out = Path(__file__).resolve().parents[1] / "_apify_yt_out/phil.report"
out.mkdir(parents=True, exist_ok=True)


def run(name, actor, inp):
    try:
        r = httpx.post(f"https://api.apify.com/v2/acts/{actor}/runs", json=inp, headers=h, timeout=60)
        if r.status_code >= 400:
            return {"error": r.text[:400]}
        rid = r.json()["data"]["id"]
        for _ in range(90):
            time.sleep(3)
            st = httpx.get(f"https://api.apify.com/v2/actor-runs/{rid}", headers=h).json()["data"]
            if st["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        items = httpx.get(
            f"https://api.apify.com/v2/datasets/{st['defaultDatasetId']}/items",
            headers=h,
            params={"limit": 100},
        ).json()
        (out / f"{name}.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        vids = []
        for row in items:
            if row.get("error"):
                continue
            vid = row.get("id") or row.get("videoId")
            if not vid:
                m = re.search(r"v=([a-zA-Z0-9_-]{11})", str(row.get("url") or ""))
                if m:
                    vid = m.group(1)
            if vid:
                vids.append((vid, row.get("viewCount"), row.get("numberOfSubscribers")))
        return {"status": st["status"], "items": len(items), "videos": len(vids), "first": items[0] if items else None, "vids": vids[:5]}
    except Exception as e:
        return {"error": str(e)}


for name, actor, inp in ACTORS:
    print(name, json.dumps(run(name, actor, inp), ensure_ascii=False)[:500])
