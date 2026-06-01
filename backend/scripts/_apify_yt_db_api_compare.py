import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from accounts.models import Account, Platform, Post
from platforms.youtube.scraper import fetch_youtube_channel

acc = Account.objects.get(platform=Platform.YOUTUBE, username="phil.report")
db = {p.external_id: p for p in Post.objects.filter(account=acc)}
api = fetch_youtube_channel("phil.report")
ap = {p["external_id"]: p for p in api.get("_posts", [])}

print(f"followers db={acc.follower_count} api={api.get('follower_count')}")
print(f"posts db={len(db)} api={len(ap)} common={len(set(db) & set(ap))}")
common = set(db) & set(ap)
view_ok = view_diff = 0
for sc in common:
    dv, av = int(db[sc].view_count or 0), int(ap[sc].view_count or 0)
    if dv == av:
        view_ok += 1
    else:
        view_diff += 1
        print(f"  {sc} views db={dv} api={av}")
print(f"views OK={view_ok} DIFF={view_diff}")
print("only_db", sorted(set(db) - set(ap)))
print("only_api", sorted(set(ap) - set(db)))
