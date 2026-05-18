"""
Экспорт / импорт полного снимка аккаунтов и постов в CSV (несколько секций в одном файле).
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Account, Platform, Post, Profile, AccountSnapshot, PostSnapshot

SECTION_ACCOUNTS = "ACCOUNTS"
SECTION_POSTS = "POSTS"
SECTION_PROFILES = "PROFILES"
SECTION_ACCOUNT_SNAPSHOTS = "ACCOUNT_SNAPSHOTS"
SECTION_POST_SNAPSHOTS = "POST_SNAPSHOTS"


def _bool_csv(value: bool) -> str:
    return "1" if value else "0"


def _parse_bool(cell: str, *, default: bool = False) -> bool:
    v = (cell or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "да")


def build_snapshot_csv() -> bytes:
    """UTF-8 с BOM, секции # PROFILES, # ACCOUNTS, # POSTS и исторические snapshots."""
    out = io.StringIO(newline="")
    out.write("\ufeff")

    out.write(f"# {SECTION_PROFILES}\n")
    prof_headers = ["id", "name", "color", "description", "avatar_url", "is_hidden"]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(prof_headers)
    for p in Profile.objects.order_by("id"):
        w.writerow([
            p.id,
            p.name,
            p.color,
            p.description,
            p.avatar_url,
            _bool_csv(p.is_hidden),
        ])

    out.write("\n")
    out.write(f"# {SECTION_ACCOUNTS}\n")
    acc_headers = [
        "id", "username", "platform", "profile_id", "profile_name", "profile_color",
        "display_name", "avatar_url", "bio",
        "follower_count", "like_count", "view_count", "post_count",
        "link_click_count", "profile_unavailable",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(acc_headers)
    for a in Account.objects.select_related("profile").order_by("id"):
        w.writerow([
            a.id,
            a.username,
            a.platform,
            a.profile_id or "",
            (a.profile.name if a.profile else ""),
            (a.profile.color if a.profile else ""),
            a.display_name,
            a.avatar_url,
            a.bio,
            a.follower_count,
            a.like_count,
            a.view_count,
            a.post_count,
            a.link_click_count,
            _bool_csv(a.profile_unavailable),
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

    out.write(f"\n# {SECTION_ACCOUNT_SNAPSHOTS}\n")
    acc_snap_headers = [
        "account_platform", "account_username", "date",
        "follower_count", "like_count", "view_count", "post_count", "link_click_count",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(acc_snap_headers)
    for s in AccountSnapshot.objects.select_related("account").order_by("account_id", "date"):
        a = s.account
        w.writerow([
            a.platform,
            a.username,
            s.date.isoformat(),
            s.follower_count,
            s.like_count,
            s.view_count,
            s.post_count,
            s.link_click_count,
        ])

    out.write(f"\n# {SECTION_POST_SNAPSHOTS}\n")
    post_snap_headers = [
        "account_platform", "account_username", "post_external_id", "date",
        "view_count", "like_count", "comment_count",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(post_snap_headers)
    for s in PostSnapshot.objects.select_related("post__account").order_by("post_id", "date"):
        p = s.post
        a = p.account
        w.writerow([
            a.platform,
            a.username,
            p.external_id,
            s.date.isoformat(),
            s.view_count,
            s.like_count,
            s.comment_count,
        ])

    return out.getvalue().encode("utf-8")


def _parse_sections(text: str) -> dict[str, list[list[str]]]:
    lines = text.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")

    raw_sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            part = stripped.lstrip("#").strip().upper()
            if part in {
                SECTION_PROFILES,
                SECTION_ACCOUNTS,
                SECTION_POSTS,
                SECTION_ACCOUNT_SNAPSHOTS,
                SECTION_POST_SNAPSHOTS,
            }:
                current = part
                raw_sections.setdefault(current, [])
            else:
                current = None
            continue
        if current is not None:
            raw_sections[current].append(line)

    sections: dict[str, list[list[str]]] = {}
    for sec, raw_lines in raw_sections.items():
        block = "\n".join(raw_lines).strip()
        if not block:
            sections[sec] = []
            continue
        reader = csv.reader(io.StringIO(block))
        sections[sec] = [row for row in reader if row and any((c or "").strip() for c in row)]

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


def _resolve_profile(*, profile_id_raw: str, profile_name_raw: str, profile_color_raw: str) -> int | None:
    pid = _parse_profile_id(profile_id_raw)
    if pid is not None:
        return pid

    name = (profile_name_raw or "").strip()
    if not name:
        return None
    color = (profile_color_raw or "").strip() or "#71717a"

    existing = Profile.objects.filter(name=name).order_by("id").first()
    if existing:
        if color and existing.color != color:
            existing.color = color
            existing.save(update_fields=["color"])
        return existing.id

    created = Profile.objects.create(name=name, color=color)
    return created.id


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


def _parse_iso_datetime(cell: str):
    cell = (cell or "").strip()
    if not cell:
        return None
    for raw in (cell.replace("Z", "+00:00"), cell):
        try:
            dt = datetime.fromisoformat(raw)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except ValueError:
            continue
    return None


def _parse_posted_at(cell: str):
    return _parse_iso_datetime(cell)


def _parse_date(cell: str):
    cell = (cell or "").strip()
    if not cell:
        return None
    dt = _parse_iso_datetime(cell)
    if dt is not None:
        return dt.date()
    try:
        return datetime.fromisoformat(cell).date()
    except ValueError:
        return None


def import_snapshot_csv(uploaded_file) -> dict[str, Any]:
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    sections = _parse_sections(text)
    prof_rows = sections.get(SECTION_PROFILES, [])
    acc_rows = sections.get(SECTION_ACCOUNTS, [])
    post_rows = sections.get(SECTION_POSTS, [])
    acc_snap_rows = sections.get(SECTION_ACCOUNT_SNAPSHOTS, [])
    post_snap_rows = sections.get(SECTION_POST_SNAPSHOTS, [])

    result: dict[str, Any] = {
        "accounts_created": 0,
        "accounts_updated": 0,
        "posts_created": 0,
        "posts_updated": 0,
        "account_snapshots_upserted": 0,
        "post_snapshots_upserted": 0,
        "errors": [],
    }

    if not prof_rows and not acc_rows and not post_rows and not acc_snap_rows and not post_snap_rows:
        result["errors"].append(
            {
                "section": "",
                "row": 0,
                "message": "Нет секций PROFILES/ACCOUNTS/POSTS/ACCOUNT_SNAPSHOTS/POST_SNAPSHOTS в файле",
            }
        )
        return result

    today = timezone.now().date()

    def row_err(section: str, row_idx: int, msg: str):
        result["errors"].append({"section": section, "row": row_idx, "message": msg})

    # ── PROFILES ──
    if prof_rows:
        header = [c.strip() for c in prof_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}

        def has_col(name: str) -> bool:
            return name.lower() in hmap

        if "name" not in hmap:
            row_err(SECTION_PROFILES, 1, "В шапке PROFILES нужна колонка name")
        else:
            with transaction.atomic():
                for rnum, row in enumerate(prof_rows[1:], start=2):
                    if not row or not any((c or "").strip() for c in row):
                        continue

                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    name = (col("name") or "").strip()
                    color = (col("color") or "").strip() or "#71717a"
                    if not name:
                        row_err(SECTION_PROFILES, rnum, "Пустое имя профиля")
                        continue
                    obj = Profile.objects.filter(name=name).order_by("id").first()
                    created = False
                    if obj is None:
                        obj = Profile.objects.create(name=name, color=color)
                        created = True
                    update_fields: list[str] = []
                    if (not created) and color and obj.color != color:
                        obj.color = color
                        update_fields.append("color")
                    if has_col("description"):
                        obj.description = col("description")
                        update_fields.append("description")
                    if has_col("avatar_url"):
                        obj.avatar_url = col("avatar_url")
                        update_fields.append("avatar_url")
                    if has_col("is_hidden"):
                        obj.is_hidden = _parse_bool(col("is_hidden"))
                        update_fields.append("is_hidden")
                    if update_fields:
                        obj.save(update_fields=list(dict.fromkeys(update_fields)))

    # ── ACCOUNTS ──
    if acc_rows:
        header = [c.strip() for c in acc_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}

        def has_col(name: str) -> bool:
            return name.lower() in hmap

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

                    prof = _resolve_profile(
                        profile_id_raw=col("profile_id"),
                        profile_name_raw=col("profile_name"),
                        profile_color_raw=col("profile_color"),
                    )
                    display_name = col("display_name")
                    avatar_url = col("avatar_url")
                    bio = col("bio")
                    try:
                        fc = _parse_int(col("follower_count"))
                        lc = _parse_int(col("like_count"))
                        vc = _parse_int(col("view_count"))
                        pc = _parse_int(col("post_count"))
                        lcc = _parse_int(col("link_click_count")) if has_col("link_click_count") else 0
                    except ValueError as e:
                        row_err(SECTION_ACCOUNTS, rnum, f"Некорректное число: {e}")
                        continue
                    profile_unavailable = (
                        _parse_bool(col("profile_unavailable")) if has_col("profile_unavailable") else False
                    )

                    defaults = {
                        "profile_id": prof,
                        "display_name": display_name,
                        "avatar_url": avatar_url,
                        "bio": bio,
                        "follower_count": fc,
                        "like_count": lc,
                        "view_count": vc,
                        "post_count": pc,
                        "link_click_count": lcc,
                        "profile_unavailable": profile_unavailable,
                    }

                    obj, created = Account.objects.get_or_create(
                        username=username,
                        platform=platform,
                        defaults=defaults,
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
                        if has_col("link_click_count"):
                            obj.link_click_count = lcc
                        if has_col("profile_unavailable"):
                            obj.profile_unavailable = profile_unavailable
                        obj.save()
                        result["accounts_updated"] += 1
                    else:
                        result["accounts_created"] += 1

                    snap, _ = obj.take_snapshot_if_needed()
                    snap.follower_count = obj.follower_count
                    snap.like_count = obj.like_count
                    snap.view_count = obj.view_count
                    snap.post_count = obj.post_count
                    snap.link_click_count = obj.link_click_count
                    snap.save(
                        update_fields=[
                            "follower_count",
                            "like_count",
                            "view_count",
                            "post_count",
                            "link_click_count",
                        ]
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

    # ── ACCOUNT_SNAPSHOTS ──
    if acc_snap_rows:
        header = [c.strip() for c in acc_snap_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}

        def has_col(name: str) -> bool:
            return name.lower() in hmap

        missing = [k for k in ("account_platform", "account_username", "date") if k not in hmap]
        if missing:
            row_err(
                SECTION_ACCOUNT_SNAPSHOTS,
                1,
                f"В шапке ACCOUNT_SNAPSHOTS не хватает колонок: {', '.join(missing)}",
            )
        else:
            with transaction.atomic():
                for rnum, row in enumerate(acc_snap_rows[1:], start=2):
                    if not row or not any(c.strip() for c in row):
                        continue

                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    pl = col("account_platform").strip().lower()
                    un = col("account_username").lstrip("@").strip()
                    snap_date = _parse_date(col("date"))
                    if not pl or not un or snap_date is None:
                        row_err(
                            SECTION_ACCOUNT_SNAPSHOTS,
                            rnum,
                            "Пустые/некорректные account_platform, account_username или date",
                        )
                        continue
                    try:
                        acc = Account.objects.get(username=un, platform=pl)
                    except Account.DoesNotExist:
                        row_err(SECTION_ACCOUNT_SNAPSHOTS, rnum, f"Аккаунт не найден: {pl}/@{un}")
                        continue

                    try:
                        fc = _parse_int(col("follower_count"))
                        lc = _parse_int(col("like_count"))
                        vc = _parse_int(col("view_count"))
                        pc = _parse_int(col("post_count"))
                        lcc = _parse_int(col("link_click_count")) if has_col("link_click_count") else None
                    except ValueError as e:
                        row_err(SECTION_ACCOUNT_SNAPSHOTS, rnum, f"Некорректное число: {e}")
                        continue

                    defaults: dict[str, int] = {
                        "follower_count": fc,
                        "like_count": lc,
                        "view_count": vc,
                        "post_count": pc,
                    }
                    if lcc is not None:
                        defaults["link_click_count"] = lcc
                    AccountSnapshot.objects.update_or_create(
                        account=acc,
                        date=snap_date,
                        defaults=defaults,
                    )
                    result["account_snapshots_upserted"] += 1

    # ── POST_SNAPSHOTS ──
    if post_snap_rows:
        header = [c.strip() for c in post_snap_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}
        missing = [
            k for k in ("account_platform", "account_username", "post_external_id", "date")
            if k not in hmap
        ]
        if missing:
            row_err(
                SECTION_POST_SNAPSHOTS,
                1,
                f"В шапке POST_SNAPSHOTS не хватает колонок: {', '.join(missing)}",
            )
        else:
            with transaction.atomic():
                for rnum, row in enumerate(post_snap_rows[1:], start=2):
                    if not row or not any(c.strip() for c in row):
                        continue

                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    pl = col("account_platform").strip().lower()
                    un = col("account_username").lstrip("@").strip()
                    ext = col("post_external_id").strip()
                    snap_date = _parse_date(col("date"))
                    if not pl or not un or not ext or snap_date is None:
                        row_err(
                            SECTION_POST_SNAPSHOTS,
                            rnum,
                            "Пустые/некорректные account_platform, account_username, post_external_id или date",
                        )
                        continue
                    try:
                        acc = Account.objects.get(username=un, platform=pl)
                    except Account.DoesNotExist:
                        row_err(SECTION_POST_SNAPSHOTS, rnum, f"Аккаунт не найден: {pl}/@{un}")
                        continue
                    try:
                        post = Post.objects.get(account=acc, external_id=ext)
                    except Post.DoesNotExist:
                        row_err(
                            SECTION_POST_SNAPSHOTS,
                            rnum,
                            f"Пост не найден: {pl}/@{un}/{ext}",
                        )
                        continue

                    try:
                        vc = _parse_int(col("view_count"))
                        lc = _parse_int(col("like_count"))
                        cc = _parse_int(col("comment_count"))
                    except ValueError as e:
                        row_err(SECTION_POST_SNAPSHOTS, rnum, f"Некорректное число: {e}")
                        continue

                    PostSnapshot.objects.update_or_create(
                        post=post,
                        date=snap_date,
                        defaults={
                            "view_count": vc,
                            "like_count": lc,
                            "comment_count": cc,
                        },
                    )
                    result["post_snapshots_upserted"] += 1

    return result
