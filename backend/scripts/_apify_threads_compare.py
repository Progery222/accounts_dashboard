"""Test 3 Threads Apify actors vs DB for theylla.zen."""
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

USERNAME = "theylla.zen"
ACCOUNT_ID = 241
MAX_POSTS = 80

ACTORS: list[tuple[str, str, dict]] = [
    (
        "makework36/threads-scraper",
        "makework36~threads-scraper",
        {"profiles": [USERNAME], "maxPosts": MAX_POSTS},
    ),
    (
        "khadinakbar/meta-threads-profile-posts-scraper",
        "khadinakbar~meta-threads-profile-posts-scraper",
        {
            "usernames": [USERNAME],
            "maxPostsPerProfile": MAX_POSTS,
            "includeProfileInfo": True,
        },
    ),
    (
        "automation-lab/threads-scraper",
        "automation-lab~threads-scraper",
        {
            "mode": "posts",
            "usernames": [USERNAME],
            "maxPosts": MAX_POSTS,
            "includeProfile": True,
        },
    ),
]


def apify_run(token: str, actor: str, inp: dict, *, poll_sec: int = 5, max_poll: int = 120) -> tuple[str, list]:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=180.0) as c:
        r = c.post(f"{base}/acts/{actor}/runs", json=inp, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"start {r.status_code}: {r.text[:600]}")
        data = r.json()["data"]
        run_id, ds_id = data["id"], data["defaultDatasetId"]
        for _ in range(max_poll):
            time.sleep(poll_sec)
            st = c.get(f"{base}/actor-runs/{run_id}", headers=headers).json()["data"]
            if st["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                if st["status"] != "SUCCEEDED":
                    raise RuntimeError(json.dumps(st, ensure_ascii=False)[:800])
                break
        else:
            raise TimeoutError(run_id)
        items = c.get(f"{base}/datasets/{ds_id}/items", headers=headers, params={"limit": 500}).json()
        return run_id, items if isinstance(items, list) else []


def post_code_from_row(row: dict) -> str:
    for k in ("postCode", "post_code", "shortcode", "code", "id", "postId", "post_id"):
        v = str(row.get(k) or "").strip()
        if re.match(r"^[A-Za-z0-9_-]{6,}$", v) and k not in ("postId", "post_id") or k in ("code", "postCode", "post_code"):
            if re.match(r"^[A-Za-z0-9_-]{6,}$", v):
                return v
    for k in ("url", "postUrl", "permalink", "post_url"):
        m = re.search(r"/post/([A-Za-z0-9_-]{6,})|/t/([A-Za-z0-9_-]{6,})", str(row.get(k) or ""))
        if m:
            return m.group(1) or m.group(2) or ""
    return ""


def views_from_row(row: dict) -> int:
    for k in (
        "viewCount",
        "views",
        "view_count",
        "playCount",
        "videoViewCount",
        "impressionCount",
        "publicViews",
    ):
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip().replace(",", "").replace(" ", "")
        if s.isdigit():
            return int(s)
        m = re.match(r"^([\d.]+)\s*([KMB])?$", s, re.I)
        if m:
            n = float(m.group(1))
            mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1)
            return int(n * mult)
    return 0


def likes_from_row(row: dict) -> int:
    for k in ("likeCount", "likes", "likesCount", "like_count"):
        v = row.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if v is not None and str(v).strip().isdigit():
            return int(str(v).strip())
    return 0


def parse_makework36(items: list) -> tuple[dict, list[dict]]:
    prof = {}
    posts = []
    for row in items:
        t = (row.get("type") or "").lower()
        if t == "profile":
            prof = row
        elif t == "post" or row.get("postCode") or row.get("text"):
            code = post_code_from_row(row) or str(row.get("postCode") or "")
            if code:
                posts.append(
                    {
                        "external_id": code,
                        "view_count": views_from_row(row),
                        "like_count": likes_from_row(row),
                        "comment_count": int(row.get("replyCount") or row.get("replies") or 0),
                    }
                )
    if not prof and items:
        for row in items:
            if row.get("followers") is not None or row.get("followerCount") is not None:
                prof = row
                break
    return prof, posts


def parse_generic(items: list) -> tuple[dict, list[dict]]:
    prof = {}
    posts = []
    for row in items:
        if (row.get("recordType") or row.get("type") or "").lower() in ("profile", "profileinfo"):
            prof = row
            continue
        if row.get("followersCount") is not None and not row.get("text") and not row.get("caption"):
            prof = prof or row
            continue
        code = post_code_from_row(row)
        if not code:
            continue
        text = row.get("text") or row.get("caption") or row.get("postText")
        if prof and not posts and not text and row.get("followerCount"):
            continue
        posts.append(
            {
                "external_id": code,
                "view_count": views_from_row(row),
                "like_count": likes_from_row(row),
                "comment_count": int(
                    row.get("replyCount")
                    or row.get("repliesCount")
                    or row.get("commentCount")
                    or row.get("comments")
                    or 0
                ),
            }
        )
    return prof, posts


PARSERS = {
    "makework36/threads-scraper": parse_makework36,
    "khadinakbar/meta-threads-profile-posts-scraper": parse_generic,
    "automation-lab/threads-scraper": parse_generic,
}


def profile_metrics(prof: dict) -> dict:
    def g(*keys):
        for k in keys:
            if prof.get(k) is not None:
                return prof.get(k)
        return None

    fc = g("followers", "followerCount", "followersCount")
    if isinstance(fc, str):
        fc = views_from_row({"views": fc}) if fc else 0
    pc = g("postCount", "postsCount", "posts_count", "mediaCount")
    return {
        "followers": int(fc or 0),
        "post_count": int(pc or 0) if str(pc or "").isdigit() else pc,
        "display_name": g("displayName", "fullName", "name", "username"),
    }


def compare_posts(apify_posts: list[dict], db_posts: dict) -> dict:
    ap = {p["external_id"]: p for p in apify_posts if p.get("external_id")}
    db_ids = set(db_posts)
    ap_ids = set(ap)
    common = db_ids & ap_ids
    view_ok = view_diff = view_miss = 0
    for sc in common:
        dv = int(db_posts[sc].view_count or 0)
        av = ap[sc]["view_count"]
        if av == 0 and dv > 0:
            view_miss += 1
        elif dv == av or (dv and abs(dv - av) / max(dv, av) < 0.1):
            view_ok += 1
        else:
            view_diff += 1
    return {
        "db_n": len(db_ids),
        "apify_n": len(ap_ids),
        "common": len(common),
        "only_db": sorted(db_ids - ap_ids),
        "only_apify": sorted(ap_ids - db_ids)[:15],
        "view_ok": view_ok,
        "view_diff": view_diff,
        "view_miss": view_miss,
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

    print("=== DB (Threads @theylla.zen) ===")
    print(
        f"id={acc.id} followers={acc.follower_count} post_count={acc.post_count} "
        f"posts_in_db={len(db_posts)} updated={acc.updated_at}"
    )
    for sc, p in sorted(db_posts.items(), key=lambda x: -int(x[1].view_count or 0)):
        print(f"  {sc} views={p.view_count} likes={p.like_count}")

    out_dir = Path(__file__).resolve().parents[1] / "_apify_threads_out" / "theylla.zen"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}

    for label, slug, inp in ACTORS:
        print(f"\n=== {label} ===")
        t0 = time.time()
        try:
            run_id, items = apify_run(token, slug, inp)
            elapsed = time.time() - t0
            safe = slug.replace("~", "_")
            (out_dir / f"{safe}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            prof, posts = PARSERS[label](items)
            pm = profile_metrics(prof)
            cmp = compare_posts(posts, db_posts)
            summary[label] = {
                "run_id": run_id,
                "elapsed_sec": round(elapsed, 1),
                "items": len(items),
                "profile": pm,
                "posts_n": len(posts),
                "compare": {k: cmp[k] for k in cmp if k != "ap"},
                "sample_keys": sorted(items[0].keys())[:20] if items else [],
            }
            print(f"  elapsed={elapsed:.1f}s items={len(items)} posts={len(posts)}")
            print(f"  profile: {pm}")
            print(
                f"  overlap db={cmp['db_n']} apify={cmp['apify_n']} common={cmp['common']} "
                f"views OK={cmp['view_ok']} DIFF={cmp['view_diff']} apify_zero={cmp['view_miss']}"
            )
            if cmp["only_db"]:
                print(f"  only_db: {cmp['only_db']}")
            if cmp["only_apify"]:
                print(f"  only_apify (first): {cmp['only_apify'][:8]}")
            if cmp["view_diff"]:
                print("  view DIFFs:")
                for sc in cmp["common"]:
                    dv = int(db_posts[sc].view_count or 0)
                    av = cmp["ap"][sc]["view_count"]
                    if dv and av and dv != av and abs(dv - av) / max(dv, av) >= 0.1:
                        print(f"    {sc} db={dv} apify={av}")
        except Exception as e:
            summary[label] = {"error": str(e)}
            print(f"  ERROR: {e}")

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out_dir}")


if __name__ == "__main__":
    main()
