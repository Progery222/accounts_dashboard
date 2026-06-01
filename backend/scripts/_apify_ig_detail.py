import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()
from accounts.models import Account, Platform, Post


def pv(r):
    return max(int(r.get("videoViewCount") or 0), int(r.get("videoPlayCount") or 0))


acc = Account.objects.get(platform=Platform.INSTAGRAM, username="phildecoded")
db = {p.external_id: p for p in Post.objects.filter(account=acc)}
posts = json.loads(Path("_apify_ig_out/phildecoded/posts.json").read_text(encoding="utf-8"))
ap = {
    r["shortCode"]: {
        "v": pv(r),
        "l": int(r.get("likesCount") or 0),
        "vv": int(r.get("videoViewCount") or 0),
        "vp": int(r.get("videoPlayCount") or 0),
    }
    for r in posts
    if r.get("shortCode")
}

vd = []
for sc in db:
    d = db[sc]
    a = ap[sc]
    dv, av = int(d.view_count or 0), a["v"]
    if dv != av:
        pct = 100 * abs(dv - av) / max(dv, av, 1)
        vd.append((sc, dv, av, a["vv"], a["vp"], abs(dv - av), pct))

ld = [(sc, int(db[sc].like_count or 0), ap[sc]["l"]) for sc in db if int(db[sc].like_count or 0) != ap[sc]["l"]]

print("VIEW DIFFS", len(vd))
for row in sorted(vd, key=lambda x: -x[5])[:12]:
    print(f"  {row[0]} db={row[1]} apify_max={row[2]} vv={row[3]} vp={row[4]} off={row[5]} pct={row[6]:.0f}")

print("LIKE DIFFS", len(ld))
for row in ld:
    print(f"  {row[0]} db={row[1]} apify={row[2]}")

match_vv = sum(1 for sc in db if int(db[sc].view_count or 0) == ap[sc]["vv"])
match_vp = sum(1 for sc in db if int(db[sc].view_count or 0) == ap[sc]["vp"])
match_max = sum(1 for sc in db if int(db[sc].view_count or 0) == ap[sc]["v"])
print(f"db equals videoViewCount: {match_vv}/30")
print(f"db equals videoPlayCount: {match_vp}/30")
print(f"db equals max(vv,vp): {match_max}/30")
