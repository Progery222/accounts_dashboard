"""
Экспорт / импорт полного снимка аккаунтов и постов в CSV (несколько секций в одном файле).
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Account, Platform, Post, Profile

SECTION_ACCOUNTS = "ACCOUNTS"
SECTION_POSTS = "POSTS"


def build_snapshot_csv() -> bytes:
    """UTF-8 с BOM, секции # ACCOUNTS и # POSTS."""
    out = io.StringIO(newline="")
    out.write("\ufeff")

    # —— ACCOUNTS ——
    out.write(f"# {SECTION_ACCOUNTS}\n")
    acc_headers = [
        "id", "username", "platform", "profile_id", "display_name", "avatar_url", "bio",
        "follower_count", "like_count", "view_count", "post_count",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(acc_headers)
    for a in Account.objects.select_related("profile").order_by("id"):
        w.writerow([
            a.id,
            a.username,
            a.platform,
            a.profile_id or "",
            a.display_name,
            a.avatar_url,
            a.bio,
            a.follower_count,
            a.like_count,
            a.view_count,
            a.post_count,
        ])

    out.write(f"\n# {SECTION_POSTS}\n")
    post_headers = [
        "account_platform", "account_username", "external_id", "description", "hashtags",
        "thumbnail_url", "post_url", "view_count", "like_count", "comment_count", "share_count",
        "posted_at",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(post_headers)
    for p in Post.objects.select_related("account").order_by("account_id", "id"):
        acc = p.account
        posted = p.posted_at.isoformat() if p.posted_at else ""
        w.writerow([
            acc.platform,
            acc.username,
            p.external_id,
            p.description,
            json.dumps(p.hashtags or [], ensure_ascii=False),
            p.thumbnail_url,
            p.post_url,
            p.view_count,
            p.like_count,
            p.comment_count,
            p.share_count,
            posted,
        ])

    return out.getvalue().encode("utf-8")


def _parse_sections(text: str) -> dict[str, list[list[str]]]:
    lines = text.splitlines()
    # strip BOM
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")

    sections: dict[str, list[list[str]]] = {}
    current: str | None = None
    rows: list[list[str]] = []

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if current is not None:
                sections[current] = rows
            # # ACCOUNTS
            part = s.lstrip("#").strip().upper()
            if part == SECTION_ACCOUNTS or part == SECTION_POSTS:
                current = part
                rows = []
            else:
                current = None
                rows = []
            continue
        if current is None:
            continue
        r = next(csv.reader([line]))
        rows.append(r)

    if current is not None:
        sections[current] = rows

    return sections


def _parse_int(v: str, default: int = 0) -> int:
    v = (v or "").strip()
    if not v:
        return default
    return int(float(v))


def _parse_profile_id(v: str) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        pid = int(v)
    except ValueError:
        return None
    if not Profile.objects.filter(pk=pid).exists():
        return None
    return pid


def _parse_hashtags(cell: str) -> list[str]:
    cell = (cell or "").strip()
    if not cell:
        return []
    if cell.startswith("["):
        try:
            data = json.loads(cell)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
    return [t.strip() for t in cell.split(";") if t.strip()]


def _parse_posted_at(cell: str):
    cell = (cell or "").strip()
    if not cell:
        return None
    try:
        dt = datetime.fromisoformat(cell.replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except ValueError:
        return None


def import_snapshot_csv(uploaded_file) -> dict[str, Any]:
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    sections = _parse_sections(text)
    acc_rows = sections.get(SECTION_ACCOUNTS, [])
    post_rows = sections.get(SECTION_POSTS, [])

    result: dict[str, Any] = {
        "accounts_created": 0,
        "accounts_updated": 0,
        "posts_created": 0,
        "posts_updated": 0,
        "errors": [],
    }

    if not acc_rows and not post_rows:
        result["errors"].append({"section": "", "row": 0, "message": "Нет секций ACCOUNTS или POSTS в файле"})
        return result

    today = timezone.now().date()

    def row_err(section: str, row_idx: int, msg: str):
        result["errors"].append({"section": section, "row": row_idx, "message": msg})

    # ── ACCOUNTS (первая строка — заголовок) ──
    if acc_rows:
        header = [c.strip() for c in acc_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}
        if "username" not in hmap and "user" not in hmap:
            row_err(SECTION_ACCOUNTS, 1, "В шапке ACCOUNTS нужна колонка username")
        elif "platform" not in hmap:
            row_err(SECTION_ACCOUNTS, 1, "В шапке ACCOUNTS нужна колонка platform")
        else:
            if "username" not in hmap and "user" in hmap:
                hmap["username"] = hmap["user"]
            valid_plats = {v for v, _ in Platform.choices}
            with transaction.atomic():
                for rnum, row in enumerate(acc_rows[1:], start=2):
                    if not row or not any(c.strip() for c in row):
                        continue
                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    username = col("username") or col("user")
                    username = username.lstrip("@").strip()
                    platform = col("platform").strip().lower()
                    if not username or not platform:
                        row_err(SECTION_ACCOUNTS, rnum, "Пустой username или platform")
                        continue
                    if platform not in valid_plats:
                        row_err(SECTION_ACCOUNTS, rnum, f"Неизвестная платформа: {platform}")
                        continue

                    prof = _parse_profile_id(col("profile_id"))
                    display_name = col("display_name")
                    avatar_url = col("avatar_url")
                    bio = col("bio")
                    try:
                        fc = _parse_int(col("follower_count"))
                        lc = _parse_int(col("like_count"))
                        vc = _parse_int(col("view_count"))
                        pc = _parse_int(col("post_count"))
                    except ValueError as e:
                        row_err(SECTION_ACCOUNTS, rnum, f"Некорректное число: {e}")
                        continue

                    obj, created = Account.objects.get_or_create(
                        username=username,
                        platform=platform,
                        defaults={
                            "profile_id": prof,
                            "display_name": display_name,
                            "avatar_url": avatar_url,
                            "bio": bio,
                            "follower_count": fc,
                            "like_count": lc,
                            "view_count": vc,
                            "post_count": pc,
                        },
                    )
                    if not created:
                        obj.profile_id = prof
                        obj.display_name = display_name
                        obj.avatar_url = avatar_url
                        obj.bio = bio
                        obj.follower_count = fc
                        obj.like_count = lc
                        obj.view_count = vc
                        obj.post_count = pc
                        obj.save()
                        result["accounts_updated"] += 1
                    else:
                        result["accounts_created"] += 1

                    snap, _ = obj.take_snapshot_if_needed()
                    snap.follower_count = obj.follower_count
                    snap.like_count = obj.like_count
                    snap.view_count = obj.view_count
                    snap.post_count = obj.post_count
                    snap.save(
                        update_fields=["follower_count", "like_count", "view_count", "post_count"]
                    )

    # ── POSTS ──
    if post_rows:
        header = [c.strip() for c in post_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}
        missing = [k for k in ("account_platform", "account_username", "external_id") if k not in hmap]
        if missing:
            row_err(SECTION_POSTS, 1, f"В шапке POSTS не хватает колонок: {', '.join(missing)}")
        else:
            with transaction.atomic():
                for rnum, row in enumerate(post_rows[1:], start=2):
                    if not row or not any(c.strip() for c in row):
                        continue

                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    pl = col("account_platform").strip().lower()
                    un = col("account_username").lstrip("@").strip()
                    ext = col("external_id").strip()
                    if not pl or not un or not ext:
                        row_err(SECTION_POSTS, rnum, "Пустые account_platform, account_username или external_id")
                        continue
                    try:
                        acc = Account.objects.get(username=un, platform=pl)
                    except Account.DoesNotExist:
                        row_err(SECTION_POSTS, rnum, f"Аккаунт не найден: {pl}/@{un}")
                        continue

                    description = col("description")
                    hashtags = _parse_hashtags(col("hashtags"))
                    thumbnail_url = col("thumbnail_url")
                    post_url = col("post_url")
                    try:
                        view_count = _parse_int(col("view_count"))
                        like_count = _parse_int(col("like_count"))
                        comment_count = _parse_int(col("comment_count"))
                        share_count = _parse_int(col("share_count"))
                    except ValueError as e:
                        row_err(SECTION_POSTS, rnum, f"Некорректное число: {e}")
                        continue
                    posted_at = _parse_posted_at(col("posted_at"))

                    post, created = Post.objects.get_or_create(
                        account=acc,
                        external_id=ext,
                        defaults={
                            "description": description,
                            "hashtags": hashtags,
                            "thumbnail_url": thumbnail_url,
                            "post_url": post_url,
                            "view_count": view_count,
                            "like_count": like_count,
                            "comment_count": comment_count,
                            "share_count": share_count,
                            "posted_at": posted_at,
                        },
                    )
                    if not created:
                        post.description = description
                        post.hashtags = hashtags
                        post.thumbnail_url = thumbnail_url
                        post.post_url = post_url
                        post.view_count = view_count
                        post.like_count = like_count
                        post.comment_count = comment_count
                        post.share_count = share_count
                        post.posted_at = posted_at
                        post.save()
                        result["posts_updated"] += 1
                    else:
                        result["posts_created"] += 1

                    post.take_snapshot_if_needed()
                    post.snapshots.filter(date=today).update(
                        view_count=post.view_count,
                        like_count=post.like_count,
                        comment_count=post.comment_count,
                    )

    return result
