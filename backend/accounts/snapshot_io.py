"""
Экспорт / импорт полного снимка аккаунтов и постов в CSV (несколько секций в одном файле).
"""
from __future__ import annotations

import csv
import io
import json
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from django.db import transaction
from django.db.utils import OperationalError
from django.utils import timezone

from .models import (
    Account,
    AccountSnapshot,
    AutoRefreshPoint,
    Platform,
    Post,
    PostSnapshot,
    Profile,
)

SECTION_ACCOUNTS = "ACCOUNTS"
SECTION_POSTS = "POSTS"
SECTION_PROFILES = "PROFILES"
SECTION_ACCOUNT_SNAPSHOTS = "ACCOUNT_SNAPSHOTS"
SECTION_POST_SNAPSHOTS = "POST_SNAPSHOTS"
SECTION_AUTO_REFRESH_POINTS = "AUTO_REFRESH_POINTS"

POST_SNAPSHOT_IMPORT_CHUNK = 400
_SNAPSHOT_IMPORT_DEADLOCK_RETRIES = 6

# Ключ поста в CSV: (platform, username lower, external_id)
PostExportKey = tuple[str, str, str]


def _is_deadlock_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    if "deadlock" in str(exc).lower():
        return True
    cause = getattr(exc, "__cause__", None)
    pgcode = getattr(cause, "pgcode", None) or getattr(cause, "sqlstate", None)
    return pgcode == "40P01"


def _run_with_deadlock_retry(fn: Callable[[], Any], *, max_attempts: int = _SNAPSHOT_IMPORT_DEADLOCK_RETRIES) -> Any:
    last: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except OperationalError as exc:
            last = exc
            if not _is_deadlock_error(exc) or attempt >= max_attempts - 1:
                raise
            time.sleep(min(2.0, 0.08 * (2 ** attempt)) + random.random() * 0.05)
    if last is not None:
        raise last
    raise RuntimeError("deadlock retry exhausted")  # pragma: no cover


def _norm_username(username: str) -> str:
    return (username or "").lstrip("@").strip()


def _post_export_key(platform: str, username: str, external_id: str) -> PostExportKey:
    return (
        (platform or "").strip().lower(),
        _norm_username(username).lower(),
        (external_id or "").strip(),
    )


def _resolve_account(platform: str, username: str) -> Account:
    """Поиск аккаунта без учёта регистра username (как в экспорте/импорте CSV)."""
    pl = (platform or "").strip().lower()
    un = _norm_username(username)
    return Account.objects.get(username__iexact=un, platform=pl)


def _bool_csv(value: bool) -> str:
    return "1" if value else "0"


def _parse_bool(cell: str, *, default: bool = False) -> bool:
    v = (cell or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "да")


def _post_to_csv_row(post: Post) -> list:
    acc = post.account
    posted = post.posted_at.isoformat() if post.posted_at else ""
    return [
        acc.platform,
        acc.username,
        post.external_id,
        post.description,
        json.dumps(post.hashtags or [], ensure_ascii=False),
        post.thumbnail_url,
        post.post_url,
        post.view_count,
        post.like_count,
        post.comment_count,
        post.share_count,
        posted,
    ]


def _collect_posts_for_export() -> dict[PostExportKey, Post]:
    """
    Все посты для секции POSTS: из Post и из PostSnapshot (на случай рассинхрона).
    Каждый post_external_id из POST_SNAPSHOTS должен иметь строку в POSTS.
    """
    posts: dict[PostExportKey, Post] = {}
    for post in Post.objects.select_related("account").order_by("account_id", "id"):
        acc = post.account
        key = _post_export_key(acc.platform, acc.username, post.external_id)
        if key[0] and key[1] and key[2]:
            posts[key] = post
    for snap in PostSnapshot.objects.select_related("post__account").order_by("post_id", "id"):
        post = snap.post
        acc = post.account
        key = _post_export_key(acc.platform, acc.username, post.external_id)
        if key[0] and key[1] and key[2]:
            posts.setdefault(key, post)
    return posts


def _normalize_imported_chart_times(
    rows: list[dict[str, Any]],
    *,
    window_hours: int = 24,
    min_span_hours: float = 2.0,
    force: bool = False,
) -> bool:
    """
    После импорта CSV метки measured_at часто «из прошлого» или все в одну секунду.
    Live-график по оси X тогда даёт плато + вертикальный скачок справа.

    Равномерно раскладывает точки по [now-window, now], сохраняя порядок.
    Возвращает True, если время было пересчитано.
    """
    if not rows:
        return False
    now = timezone.now()
    window_start = now - timedelta(hours=window_hours)
    times = [r["measured_at"] for r in rows if r.get("measured_at")]
    if not times:
        return False
    t_min, t_max = min(times), max(times)
    span_src = (t_max - t_min).total_seconds()
    collapsed = span_src < min_span_hours * 3600
    stale = t_max < window_start
    if not force and not stale and not collapsed:
        return False

    span_dst = (now - window_start).total_seconds()
    n = len(rows)
    if span_src <= 0:
        for i, row in enumerate(rows):
            frac = i / max(1, n - 1)
            new_dt = window_start + timedelta(seconds=frac * span_dst)
            row["measured_at"] = new_dt
            row["local_date"] = timezone.localtime(new_dt).date()
        return True

    for row in rows:
        dt = row.get("measured_at")
        if not dt:
            continue
        frac = (dt - t_min).total_seconds() / span_src
        new_dt = window_start + timedelta(seconds=frac * span_dst)
        row["measured_at"] = new_dt
        row["local_date"] = timezone.localtime(new_dt).date()
    return True


def _chart_totals_look_flat(rows: list[dict[str, Any]]) -> bool:
    totals = [int(r.get("view_count_total") or 0) for r in rows]
    if len(totals) < 2:
        return False
    end = max(totals)
    spread = max(totals) - min(totals)
    if spread < max(800, end * 0.003):
        return True
    # Импорт: десятки точек с одним total и скачок только в конце — spread большой, график всё равно «плоский».
    from collections import Counter

    _mode, freq = Counter(totals).most_common(1)[0]
    return freq >= max(3, int(len(rows) * 0.65))


def _normalize_imported_chart_totals(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
) -> bool:
    """
    После импорта CSV все точки часто несут один и тот же view_count_total (срез «сейчас»),
    а дельты по часам — нули. График Live тогда плоский, а справа — скачок до актуального TOTAL.

    Пересобирает view_count_total по view_delta_from_prev_point / platform_deltas / day_delta.
    """
    if not rows or len(rows) < 2:
        return False
    rows.sort(key=lambda r: r["measured_at"])
    if not force and not _chart_totals_look_flat(rows):
        return False

    end_total = int(rows[-1].get("view_count_total") or 0)
    day_delta = int(rows[-1].get("view_delta_from_day_start") or 0)
    if day_delta <= 0:
        day_delta = sum(max(0, int(r.get("view_delta_from_prev_point") or 0)) for r in rows)

    alloc = [max(0, int(r.get("view_delta_from_prev_point") or 0)) for r in rows]
    if sum(alloc) <= 0:
        alloc = []
        for r in rows:
            pd = r.get("platform_deltas") or {}
            if isinstance(pd, dict):
                alloc.append(sum(max(0, int(v)) for v in pd.values()))
            else:
                alloc.append(0)

    if sum(alloc) <= 0 and day_delta > 0:
        n = len(rows)
        per = day_delta // n
        rem = day_delta % n
        alloc = [per + (1 if i < rem else 0) for i in range(n)]

    if sum(alloc) <= 0:
        return False

    if day_delta <= 0:
        day_delta = sum(alloc)

    base = max(0, end_total - day_delta)
    cum = base
    prev_total = base
    for i, row in enumerate(rows):
        d = max(0, int(alloc[i]))
        cum += d
        row["view_count_total"] = cum
        row["view_delta_from_prev_point"] = d
        row["view_delta_from_day_start"] = cum - base
        prev_total = cum
    rows[0]["view_delta_from_prev_point"] = max(0, int(alloc[0]))
    return True


def _parse_platform_deltas(cell: str) -> dict[str, int]:
    cell = (cell or "").strip()
    if not cell:
        return {}
    try:
        data = json.loads(cell)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in data.items():
        key = str(k).strip().lower()
        if not key:
            continue
        try:
            out[key] = int(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _bulk_upsert_post_snapshots(snaps: list[PostSnapshot]) -> None:
    if not snaps:
        return
    PostSnapshot.objects.bulk_create(
        snaps,
        update_conflicts=True,
        unique_fields=["post", "date"],
        update_fields=["view_count", "like_count", "comment_count"],
    )


def _import_post_snapshots_rows(
    post_snap_rows: list[list[str]],
    *,
    post_rows_present: bool,
    result: dict[str, Any],
    row_err: Callable[[str, int, str], None],
) -> None:
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
        return

    parsed: list[tuple[int, str, str, str, date, int, int, int]] = []
    for rnum, row in enumerate(post_snap_rows[1:], start=2):
        if not row or not any(c.strip() for c in row):
            continue

        def col(name: str, default="") -> str:
            j = hmap.get(name.lower())
            if j is None or j >= len(row):
                return default
            return row[j] if row[j] is not None else default

        pl = col("account_platform").strip().lower()
        un = _norm_username(col("account_username"))
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
            vc = _parse_int(col("view_count"))
            lc = _parse_int(col("like_count"))
            cc = _parse_int(col("comment_count"))
        except ValueError as e:
            row_err(SECTION_POST_SNAPSHOTS, rnum, f"Некорректное число: {e}")
            continue
        parsed.append((rnum, pl, un, ext, snap_date, vc, lc, cc))

    if not parsed:
        return

    # Стабильный порядок блокировок — меньше deadlock с refresh/scheduler.
    parsed.sort(key=lambda r: (r[1], r[2], r[3], r[4]))

    post_cache: dict[tuple[str, str, str], Post] = {}

    def _ensure_post(pl: str, un: str, ext: str, acc: Account, vc: int, lc: int, cc: int) -> Post:
        key = (pl, un, ext)
        cached = post_cache.get(key)
        if cached is not None:
            return cached

        def _create() -> Post:
            post, created = Post.objects.get_or_create(
                account=acc,
                external_id=ext,
                defaults={
                    "view_count": vc,
                    "like_count": lc,
                    "comment_count": cc,
                },
            )
            if created:
                result["posts_created"] += 1
            elif not post_rows_present:
                post.view_count = max(post.view_count, vc)
                post.like_count = max(post.like_count, lc)
                post.comment_count = max(post.comment_count, cc)
                post.save(update_fields=["view_count", "like_count", "comment_count"])
            post_cache[key] = post
            return post

        return _run_with_deadlock_retry(_create)

    snap_objs: list[PostSnapshot] = []
    for rnum, pl, un, ext, snap_date, vc, lc, cc in parsed:
        try:
            acc = _resolve_account(pl, un)
        except Account.DoesNotExist:
            row_err(SECTION_POST_SNAPSHOTS, rnum, f"Аккаунт не найден: {pl}/@{un}")
            continue
        post = _ensure_post(pl, un, ext, acc, vc, lc, cc)
        snap_objs.append(
            PostSnapshot(
                post=post,
                date=snap_date,
                view_count=vc,
                like_count=lc,
                comment_count=cc,
            ),
        )

    for i in range(0, len(snap_objs), POST_SNAPSHOT_IMPORT_CHUNK):
        chunk = snap_objs[i : i + POST_SNAPSHOT_IMPORT_CHUNK]

        def _upsert_chunk(c=chunk) -> None:
            with transaction.atomic():
                _bulk_upsert_post_snapshots(c)

        _run_with_deadlock_retry(_upsert_chunk)
        result["post_snapshots_upserted"] += len(chunk)


def build_snapshot_csv() -> bytes:
    """UTF-8 с BOM: профили, аккаунты, посты, снапшоты и точки графика Live (AUTO_REFRESH_POINTS)."""
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
        "link_click_count", "profile_unavailable", "updated_at",
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
            timezone.localtime(a.updated_at).isoformat() if a.updated_at else "",
        ])

    out.write(f"\n# {SECTION_POSTS}\n")
    post_headers = [
        "account_platform", "account_username", "external_id", "description", "hashtags",
        "thumbnail_url", "post_url", "view_count", "like_count", "comment_count", "share_count",
        "posted_at",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(post_headers)
    export_posts = _collect_posts_for_export()
    for key in sorted(export_posts.keys()):
        w.writerow(_post_to_csv_row(export_posts[key]))

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

    out.write(f"\n# {SECTION_AUTO_REFRESH_POINTS}\n")
    ar_headers = [
        "measured_at",
        "local_date",
        "source",
        "slot_label",
        "view_count_total",
        "view_delta_from_prev_point",
        "view_delta_from_day_start",
        "platform_deltas",
    ]
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(ar_headers)
    chart_since = timezone.now() - timedelta(days=30)
    for p in AutoRefreshPoint.objects.filter(measured_at__gte=chart_since).order_by("measured_at"):
        measured = timezone.localtime(p.measured_at).isoformat() if p.measured_at else ""
        w.writerow([
            measured,
            p.local_date.isoformat() if p.local_date else "",
            p.source or "",
            p.slot_label or "",
            p.view_count_total,
            p.view_delta_from_prev_point,
            p.view_delta_from_day_start,
            json.dumps(p.platform_deltas or {}, ensure_ascii=False),
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
                SECTION_AUTO_REFRESH_POINTS,
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
    """
    Привязка профиля при импорте CSV.

    Имя профиля важнее числового id: на другой БД те же pk означают другой профиль
    (локально id=4 «Фил», на сервере после импорта PROFILES id=4 может быть «AI FARM»).
    """
    name = (profile_name_raw or "").strip()
    color = (profile_color_raw or "").strip() or "#71717a"

    if name:
        existing = Profile.objects.filter(name=name).order_by("id").first()
        if existing:
            if color and existing.color != color:
                existing.color = color
                existing.save(update_fields=["color"])
            return existing.id
        return Profile.objects.create(name=name, color=color).id

    pid = _parse_profile_id(profile_id_raw)
    if pid is not None:
        return pid
    return None


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
    auto_refresh_rows = sections.get(SECTION_AUTO_REFRESH_POINTS, [])

    result: dict[str, Any] = {
        "accounts_created": 0,
        "accounts_updated": 0,
        "posts_created": 0,
        "posts_updated": 0,
        "account_snapshots_upserted": 0,
        "post_snapshots_upserted": 0,
        "auto_refresh_points_imported": 0,
        "auto_refresh_chart_times_remapped": False,
        "auto_refresh_chart_totals_rebuilt": False,
        "errors": [],
    }

    if (
        not prof_rows
        and not acc_rows
        and not post_rows
        and not acc_snap_rows
        and not post_snap_rows
        and not auto_refresh_rows
    ):
        result["errors"].append(
            {
                "section": "",
                "row": 0,
                "message": (
                    "Нет секций PROFILES/ACCOUNTS/POSTS/ACCOUNT_SNAPSHOTS/"
                    "POST_SNAPSHOTS/AUTO_REFRESH_POINTS в файле"
                ),
            }
        )
        return result

    today = timezone.now().date()
    has_post_snapshots_section = bool(post_snap_rows)
    has_account_snapshots_section = bool(acc_snap_rows)

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
                    updated_at_parsed = None
                    if has_col("updated_at"):
                        raw_updated = (col("updated_at") or "").strip()
                        if raw_updated:
                            updated_at_parsed = _parse_iso_datetime(raw_updated)
                            if updated_at_parsed is None:
                                row_err(SECTION_ACCOUNTS, rnum, f"Некорректный updated_at: {raw_updated!r}")
                                continue

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

                    if updated_at_parsed is not None:
                        Account.objects.filter(pk=obj.pk).update(updated_at=updated_at_parsed)

                    if not has_account_snapshots_section:
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
                    un = _norm_username(col("account_username"))
                    ext = col("external_id").strip()
                    if not pl or not un or not ext:
                        row_err(SECTION_POSTS, rnum, "Пустые account_platform, account_username или external_id")
                        continue
                    try:
                        acc = _resolve_account(pl, un)
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

                    if not has_post_snapshots_section:
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
                    un = _norm_username(col("account_username"))
                    snap_date = _parse_date(col("date"))
                    if not pl or not un or snap_date is None:
                        row_err(
                            SECTION_ACCOUNT_SNAPSHOTS,
                            rnum,
                            "Пустые/некорректные account_platform, account_username или date",
                        )
                        continue
                    try:
                        acc = _resolve_account(pl, un)
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
        _import_post_snapshots_rows(
            post_snap_rows,
            post_rows_present=bool(post_rows),
            result=result,
            row_err=row_err,
        )

    # ── AUTO_REFRESH_POINTS (графики Live / auto-refresh-series) ──
    if auto_refresh_rows:
        header = [c.strip() for c in auto_refresh_rows[0]]
        hmap = {h.lower(): i for i, h in enumerate(header)}
        missing = [k for k in ("measured_at", "view_count_total") if k not in hmap]
        if missing:
            row_err(
                SECTION_AUTO_REFRESH_POINTS,
                1,
                f"В шапке AUTO_REFRESH_POINTS не хватает колонок: {', '.join(missing)}",
            )
        else:
            data_rows = [
                row for row in auto_refresh_rows[1:]
                if row and any((c or "").strip() for c in row)
            ]
            if data_rows:
                parsed_rows: list[dict[str, Any]] = []
                for rnum, row in enumerate(data_rows, start=2):
                    def col(name: str, default="") -> str:
                        j = hmap.get(name.lower())
                        if j is None or j >= len(row):
                            return default
                        return row[j] if row[j] is not None else default

                    measured_at = _parse_iso_datetime(col("measured_at"))
                    if measured_at is None:
                        row_err(
                            SECTION_AUTO_REFRESH_POINTS,
                            rnum,
                            "Некорректный measured_at",
                        )
                        continue
                    local_date = _parse_date(col("local_date"))
                    if local_date is None:
                        local_date = timezone.localtime(measured_at).date()
                    try:
                        view_total = _parse_int(col("view_count_total"))
                        view_prev = _parse_int(col("view_delta_from_prev_point"))
                        view_day = _parse_int(col("view_delta_from_day_start"))
                    except ValueError as e:
                        row_err(SECTION_AUTO_REFRESH_POINTS, rnum, f"Некорректное число: {e}")
                        continue
                    platform_deltas = _parse_platform_deltas(col("platform_deltas"))
                    parsed_rows.append({
                        "measured_at": measured_at,
                        "local_date": local_date,
                        "source": (col("source") or "import").strip()[:32],
                        "slot_label": (col("slot_label") or "").strip()[:32],
                        "view_count_total": view_total,
                        "view_delta_from_prev_point": view_prev,
                        "view_delta_from_day_start": view_day,
                        "platform_deltas": platform_deltas,
                    })

                if parsed_rows:
                    parsed_rows.sort(key=lambda r: r["measured_at"])
                    result["auto_refresh_chart_times_remapped"] = _normalize_imported_chart_times(
                        parsed_rows,
                    )
                    result["auto_refresh_chart_totals_rebuilt"] = _normalize_imported_chart_totals(
                        parsed_rows,
                    )
                    with transaction.atomic():
                        AutoRefreshPoint.objects.all().delete()
                        for row in parsed_rows:
                            AutoRefreshPoint.objects.create(
                                measured_at=row["measured_at"],
                                local_date=row["local_date"],
                                source=row["source"],
                                slot_label=row["slot_label"],
                                view_count_total=row["view_count_total"],
                                view_delta_from_prev_point=row["view_delta_from_prev_point"],
                                view_delta_from_day_start=row["view_delta_from_day_start"],
                                platform_deltas=row["platform_deltas"],
                            )
                            result["auto_refresh_points_imported"] += 1

    return result
