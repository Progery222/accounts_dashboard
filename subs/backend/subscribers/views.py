"""API раздела «Подписчики» (отдельная БД subs + синхронизация с дашбордом)."""

import csv
import json
import os
from collections import Counter
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q
from django.http import FileResponse, StreamingHttpResponse
from django.test import RequestFactory
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request as DRFRequest
from rest_framework.response import Response

from .dashboard_sync import (
    dashboard_delete_audience_member_by_username,
    dashboard_refresh_account,
    dashboard_stop_audience_scrape,
    import_audience_into_subs,
    sync_profiles_and_accounts,
)
from .export_presumed import CSV_PRESUMED_HEADERS, ND, presumed_csv_column_values, presumed_csv_fields
from .models import (
    Account,
    AccountAudienceMembership,
    AudienceMember,
    Profile,
    SUBS_SUBSCRIBER_PLATFORM_VALUES,
    SUBS_SUBSCRIBER_PLATFORMS,
)
from .visibility import _apply_visibility_filters, _coerce_bool


def _parse_profile_ids_param(request) -> list[int] | None:
    """
    Непустой список id профилей subs из query: profile_ids=1,2 или несколько ключей profile_ids.
    Если параметра нет или после разбора пусто — None.
    """
    chunks = request.query_params.getlist("profile_ids")
    if not chunks:
        single = (request.query_params.get("profile_ids") or "").strip()
        if single:
            chunks = [single]
    ids: list[int] = []
    for chunk in chunks:
        for piece in str(chunk).split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                ids.append(int(piece))
            except ValueError:
                continue
    dedup = sorted(set(ids))
    return dedup or None


def _subscriber_visible_accounts_queryset(request, *, annotate_audience_count: bool = False):
    include_hidden = _coerce_bool(request.query_params.get("include_hidden"))
    include_hidden_platforms = include_hidden or _coerce_bool(
        request.query_params.get("include_hidden_platforms"),
    )
    include_hidden_profiles = include_hidden or _coerce_bool(
        request.query_params.get("include_hidden_profiles"),
    )

    base = Account.objects.filter(
        platform__in=SUBS_SUBSCRIBER_PLATFORMS,
    ).select_related("profile")
    platform = (request.query_params.get("platform") or "").strip().lower()
    if platform in SUBS_SUBSCRIBER_PLATFORM_VALUES:
        base = base.filter(platform=platform)
    multi_profile_ids = _parse_profile_ids_param(request)
    profile_id = (request.query_params.get("profile_id") or "").strip()
    if multi_profile_ids is not None:
        base = base.filter(profile_id__in=multi_profile_ids)
    elif profile_id == "none":
        base = base.filter(profile__isnull=True)
    elif profile_id:
        try:
            base = base.filter(profile_id=int(profile_id))
        except (TypeError, ValueError):
            pass
    base = _apply_visibility_filters(
        base,
        include_hidden_platforms=include_hidden_platforms,
        include_hidden_profiles=include_hidden_profiles,
    )
    base = base.exclude(profile_unavailable=True)
    if annotate_audience_count:
        base = base.annotate(
            audience_count=Count("audience_memberships", distinct=True),
        )
    return base


def _members_filtered_queryset(request):
    """
    Выборка AudienceMember с теми же фильтрами, что и список /members/
    (видимые отслеживаемые аккаунты — с учётом platform, profile_id, profile_ids,
    for_account, search, only_private, member_sort).

    Возвращает (queryset, error_response). error_response — только при 400 из-за for_account.
    При отсутствии видимых аккаунтов — пустой queryset, без ошибки.
    """
    visible_ids = list(
        _subscriber_visible_accounts_queryset(request).values_list("pk", flat=True),
    )
    if not visible_ids:
        return AudienceMember.objects.none(), None

    search = (request.query_params.get("search") or "").strip()

    for_account_id = None
    raw_for = (request.query_params.get("for_account") or "").strip()
    if raw_for:
        try:
            cand = int(raw_for)
        except (TypeError, ValueError):
            return None, Response(
                {"detail": "Некорректный идентификатор аккаунта."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if cand not in set(visible_ids):
            return None, Response(
                {"detail": "Аккаунт не входит в текущую выборку."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for_account_id = cand

    if for_account_id is not None:
        member_id_qs = (
            AccountAudienceMembership.objects.filter(account_id=for_account_id)
            .values_list("member_id", flat=True)
            .distinct()
        )
    else:
        member_id_qs = (
            AccountAudienceMembership.objects.filter(account_id__in=visible_ids)
            .values_list("member_id", flat=True)
            .distinct()
        )

    mem_qs = AudienceMember.objects.filter(pk__in=member_id_qs).annotate(
        follows_tracked_accounts=Count(
            "memberships",
            filter=Q(memberships__account_id__in=visible_ids),
            distinct=True,
        ),
    )

    if search:
        mem_qs = mem_qs.filter(
            Q(username__icontains=search)
            | Q(display_name__icontains=search)
            | Q(bio__icontains=search),
        )

    if _coerce_bool(request.query_params.get("only_private")):
        mem_qs = mem_qs.filter(is_private=True)

    sort = (request.query_params.get("member_sort") or "").strip().lower()
    if sort == "follows_desc":
        mem_qs = mem_qs.order_by("-follows_tracked_accounts", "platform", "username")
    elif sort == "follows_asc":
        mem_qs = mem_qs.order_by("follows_tracked_accounts", "platform", "username")
    elif sort == "username_desc":
        mem_qs = mem_qs.order_by("-username", "platform")
    elif sort == "username_asc":
        mem_qs = mem_qs.order_by("username", "platform")
    else:
        mem_qs = mem_qs.order_by("platform", "username")
    return mem_qs, None


_CSV_EXPORT_HEADER = [
    "id_subs",
    "платформа",
    "ник",
    "external_id",
    "имя",
    "url_аватара",
    "био",
    "закрытый_профиль",
    "подписчики",
    "подписки",
    "лайки",
    "наших_отслеживаемых_аккаунтов",
    "создан",
    "обновлён",
    *CSV_PRESUMED_HEADERS,
]


def _csv_row_for_member(m) -> list:
    presumed = presumed_csv_column_values(
        username=m.username or "",
        display_name=m.display_name or "",
        bio=m.bio or "",
        platform=m.platform or "",
    )
    return [
        m.id,
        m.platform,
        m.username,
        m.external_id or "",
        m.display_name or "",
        m.avatar_url or "",
        m.bio or "",
        "да" if m.is_private else "нет",
        int(m.follower_count or 0),
        int(m.following_count or 0),
        int(m.like_count or 0),
        int(getattr(m, "follows_tracked_accounts", 0) or 0),
        m.created_at.isoformat() if m.created_at else "",
        m.updated_at.isoformat() if m.updated_at else "",
        *presumed,
    ]


def _subs_last_export_dir() -> Path:
    raw = getattr(settings, "SUBS_LAST_EXPORT_DIR", None)
    if raw:
        return Path(raw)
    return Path(settings.BASE_DIR) / "var" / "subs_last_export"


def _subs_last_export_csv_path() -> Path:
    return _subs_last_export_dir() / "members_export_last.csv"


def _subs_last_export_meta_path() -> Path:
    return _subs_last_export_dir() / "members_export_last.meta.json"


def _iter_member_csv_text_chunks(mem_qs):
    buf = StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_CSV_EXPORT_HEADER)
    yield "\ufeff" + buf.getvalue()
    for m in mem_qs.iterator(chunk_size=500):
        buf.seek(0)
        buf.truncate(0)
        writer.writerow(_csv_row_for_member(m))
        yield buf.getvalue()


def _write_last_members_export_to_disk(mem_qs, *, query_string: str) -> None:
    """Полная выгрузка в members_export_last.csv + meta (без ответа клиенту)."""
    out_dir = _subs_last_export_dir()
    csv_path = _subs_last_export_csv_path()
    meta_path = _subs_last_export_meta_path()
    tmp_path = csv_path.with_suffix(".csv.tmp")
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = False
    try:
        with open(tmp_path, "wb") as out_f:
            for text in _iter_member_csv_text_chunks(mem_qs):
                out_f.write(text.encode("utf-8"))
        os.replace(tmp_path, csv_path)
        meta = {
            "generated_at": timezone.now().isoformat(),
            "query_string": query_string[:4000],
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        ok = True
    finally:
        if not ok and tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass


@api_view(["GET"])
def overview(request):
    base = _subscriber_visible_accounts_queryset(
        request,
        annotate_audience_count=True,
    )

    visible_ids = list(base.values_list("pk", flat=True))

    accounts_out = []
    for acc in base.order_by("-audience_count", "platform", "username"):
        prof = acc.profile
        accounts_out.append({
            "id": acc.id,
            "dashboard_account_id": acc.mirror_dashboard_id,
            "platform": acc.platform,
            "username": acc.username,
            "display_name": acc.display_name or "",
            "audience_count": int(acc.audience_count or 0),
            "audience_last_synced_at": (
                acc.audience_last_synced_at.isoformat()
                if acc.audience_last_synced_at
                else None
            ),
            "profile_id": (prof.id if prof else None),
            "profile_name": (prof.name if prof else None),
        })

    if not visible_ids:
        unique_total = 0
        private_total = 0
    else:
        mem_base = AudienceMember.objects.filter(
            memberships__account_id__in=visible_ids,
        ).distinct()
        unique_total = mem_base.count()
        private_total = mem_base.filter(is_private=True).count()

    synced_n = sum(1 for a in accounts_out if a["audience_last_synced_at"])
    with_data_n = sum(1 for a in accounts_out if a["audience_count"] > 0)

    return Response({
        "summary": {
            "tracked_accounts_count": len(accounts_out),
            "accounts_with_audience_rows": with_data_n,
            "accounts_synced_at_least_once": synced_n,
            "unique_subscribers_total": unique_total,
            "private_subscribers_total": private_total,
        },
        "accounts": accounts_out,
    })


@api_view(["GET"])
def members_list(request):
    mem_qs, err = _members_filtered_queryset(request)
    if err is not None:
        return err

    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(100, max(10, int(request.query_params.get("page_size") or 40)))
    except (TypeError, ValueError):
        page_size = 40

    total = mem_qs.count()
    start = (page - 1) * page_size
    slice_qs = mem_qs[start : start + page_size]

    results = []
    for m in slice_qs:
        results.append({
            "id": m.id,
            "platform": m.platform,
            "username": m.username,
            "display_name": m.display_name or "",
            "avatar_url": m.avatar_url or "",
            "bio": (m.bio or "")[:280],
            "is_private": bool(m.is_private),
            "follower_count": int(m.follower_count or 0),
            "following_count": int(m.following_count or 0),
            "like_count": int(m.like_count or 0),
            "follows_tracked_accounts": int(m.follows_tracked_accounts or 0),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    })


@api_view(["GET"])
def members_export_csv(request):
    """Полный CSV по текущим фильтрам (как у списка подписчиков), UTF-8 с BOM для Excel.
    Параллельно сохраняет копию для предпросмотра «последний экспорт»."""
    mem_qs, err = _members_filtered_queryset(request)
    if err is not None:
        return err

    out_dir = _subs_last_export_dir()
    csv_path = _subs_last_export_csv_path()
    meta_path = _subs_last_export_meta_path()
    tmp_path = csv_path.with_suffix(".csv.tmp")

    def teeing_encoded_chunks():
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = False
        try:
            with open(tmp_path, "wb") as out_f:
                for text in _iter_member_csv_text_chunks(mem_qs):
                    b = text.encode("utf-8")
                    out_f.write(b)
                    yield b
            os.replace(tmp_path, csv_path)
            meta = {
                "generated_at": timezone.now().isoformat(),
                "query_string": (request.META.get("QUERY_STRING") or "")[:4000],
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            ok = True
        finally:
            if not ok and tmp_path.is_file():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    response = StreamingHttpResponse(
        teeing_encoded_chunks(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="podpischiki_subs.csv"'
    return response


@api_view(["POST"])
def members_export_last_refresh(request):
    """
    Пересобрать сохранённый members_export_last.csv на сервере без скачивания в браузер.
    Полная выборка: include_hidden=1 и все видимые аккаунты (без фильтров платформа/профиль/поиск),
    чтобы с любого клиента был доступен один актуальный файл — в т.ч. после «Собрать для всех».
    """
    inner = RequestFactory().get("/api/subscribers/members/export.csv", {"include_hidden": "1"})
    drf_req = DRFRequest(inner)
    mem_qs, err = _members_filtered_queryset(drf_req)
    if err is not None:
        return err
    try:
        _write_last_members_export_to_disk(
            mem_qs,
            query_string="include_hidden=1 (полный отчёт; авто после «Собрать для всех»)",
        )
    except Exception as e:
        return Response(
            {"detail": f"Не удалось сформировать CSV на сервере: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return Response({"ok": True, "detail": "Последний отчёт CSV на сервере обновлён."})


@api_view(["GET"])
def members_export_last_preview(request):
    """Первые строки последнего сохранённого CSV (после «Скачать CSV» или автообновления)."""
    csv_path = _subs_last_export_csv_path()
    meta_path = _subs_last_export_meta_path()
    if not csv_path.is_file():
        return Response(
            {
                "detail": (
                    "Последний экспорт ещё не формировался. Нажмите «Скачать CSV» "
                    "или дождитесь окончания массового «Собрать для всех»."
                ),
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    try:
        lim = int(request.query_params.get("limit") or 400)
    except (TypeError, ValueError):
        lim = 400
    lim = max(20, min(lim, 800))

    headers: list[str] = []
    rows: list[list[str]] = []
    row_total = 0
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = list(next(reader))
        except StopIteration:
            return Response(
                {"detail": "Файл последнего экспорта пуст."},
                status=status.HTTP_404_NOT_FOUND,
            )
        for row in reader:
            row_total += 1
            if len(rows) < lim:
                rows.append(row)

    truncated = row_total > len(rows)
    return Response({
        "generated_at": meta.get("generated_at"),
        "query_string": meta.get("query_string") or "",
        "headers": headers,
        "rows": rows,
        "row_total": row_total,
        "preview_row_count": len(rows),
        "truncated": truncated,
    })


def _dense_rank_sorted_counts(counter: Counter[str]) -> list[dict]:
    """Сортировка по убыванию count; одинаковые count — одинаковый rank (плотное ранжирование)."""
    pairs = sorted(counter.items(), key=lambda t: (-t[1], t[0]))
    out: list[dict] = []
    prev_count: int | None = None
    rank = 0
    for label, cnt in pairs:
        if prev_count is None or cnt != prev_count:
            rank += 1
            prev_count = cnt
        out.append({"label": label, "count": cnt, "rank": rank})
    return out


def _presumed_stats_from_members_queryset(mem_qs) -> tuple[list[dict], int]:
    """
    Те же эвристики «Предполагаемый …», что в CSV, по полной выборке AudienceMember
    (без чтения members_export_last.csv).
    """
    counters: list[Counter[str]] = [Counter() for _ in CSV_PRESUMED_HEADERS]
    row_count = 0
    for m in mem_qs.iterator(chunk_size=500):
        row_count += 1
        pres = presumed_csv_fields(
            username=m.username or "",
            display_name=m.display_name or "",
            bio=m.bio or "",
            platform=m.platform or "",
        )
        for ci, title in enumerate(CSV_PRESUMED_HEADERS):
            val = str(pres.get(title) or "").strip()
            if not val or val == ND:
                continue
            counters[ci][val] += 1
    columns: list[dict] = []
    for title, counter in zip(CSV_PRESUMED_HEADERS, counters, strict=True):
        columns.append(
            {
                "header": title,
                "items": _dense_rank_sorted_counts(counter),
            },
        )
    return columns, row_count


@api_view(["GET"])
def members_presumed_stats(request):
    """
    Распределение по колонкам «Предполагаемый …» для всех подписчиков в текущих
    фильтрах (как у GET members/ и экспорта CSV), данные из БД, не из последнего файла.
    """
    mem_qs, err = _members_filtered_queryset(request)
    if err is not None:
        return err
    columns, row_count = _presumed_stats_from_members_queryset(mem_qs)
    return Response(
        {
            "generated_at": timezone.now().isoformat(),
            "columns": columns,
            "member_row_count": row_count,
            "source": "database",
        },
    )


@api_view(["GET"])
def members_export_last_presumed_stats(request):
    """
    Распределение значений по колонкам «Предполагаемый …» из последнего CSV
    (полный файл; пустые и «Нет данных» не учитываются).
    """
    csv_path = _subs_last_export_csv_path()
    meta_path = _subs_last_export_meta_path()
    if not csv_path.is_file():
        return Response(
            {
                "detail": (
                    "Последний экспорт ещё не формировался. Нажмите «Скачать CSV» "
                    "или дождитесь окончания массового «Собрать для всех»."
                ),
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            file_headers = list(next(reader))
        except StopIteration:
            return Response(
                {"detail": "Файл последнего экспорта пуст."},
                status=status.HTTP_404_NOT_FOUND,
            )

    idx_by_title = {h: i for i, h in enumerate(file_headers)}
    col_indices: list[int | None] = [idx_by_title.get(title) for title in CSV_PRESUMED_HEADERS]
    counters: list[Counter[str]] = [Counter() for _ in CSV_PRESUMED_HEADERS]

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            for ci, idx in enumerate(col_indices):
                if idx is None or idx >= len(row):
                    continue
                val = (row[idx] or "").strip()
                if not val or val == ND:
                    continue
                counters[ci][val] += 1

    columns = []
    for title, counter in zip(CSV_PRESUMED_HEADERS, counters, strict=True):
        columns.append(
            {
                "header": title,
                "items": _dense_rank_sorted_counts(counter),
            },
        )

    return Response(
        {
            "generated_at": meta.get("generated_at"),
            "columns": columns,
        },
    )


@api_view(["GET"])
def members_export_last_csv(request):
    """Повторная выдача последнего сохранённого CSV."""
    csv_path = _subs_last_export_csv_path()
    if not csv_path.is_file():
        return Response(
            {
                "detail": (
                    "Последний экспорт ещё не формировался. Нажмите «Скачать CSV» "
                    "или дождитесь окончания массового «Собрать для всех»."
                ),
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    inline = request.query_params.get("inline") in ("1", "true", "yes")
    disp = "inline" if inline else "attachment"
    resp = FileResponse(csv_path.open("rb"), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'{disp}; filename="podpischiki_subs_last.csv"'
    return resp


@api_view(["GET", "DELETE"])
def audience_member_retrieve_destroy(request, pk: int):
    """
    GET — карточка подписчика (данные в subs + на какие отслеживаемые аккаунты подписан).
    DELETE — убрать из снятой базы на дашборде (если есть mirror) и связи в subs.
    """
    visible_ids = list(
        _subscriber_visible_accounts_queryset(request).values_list("pk", flat=True),
    )
    if not visible_ids:
        return Response(
            {"detail": "Нет видимых отслеживаемых аккаунтов."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        member = AudienceMember.objects.annotate(
            follows_tracked_accounts=Count(
                "memberships",
                filter=Q(memberships__account_id__in=visible_ids),
                distinct=True,
            ),
        ).get(pk=int(pk))
    except (AudienceMember.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "Подписчик не найден."}, status=status.HTTP_404_NOT_FOUND)

    memberships = list(
        AccountAudienceMembership.objects.filter(
            member=member,
            account_id__in=visible_ids,
        ).select_related("account", "account__profile"),
    )
    if not memberships:
        return Response(
            {"detail": "Этого подписчика нет среди видимых отслеживаемых аккаунтов."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        accounts_out = []
        for mem in memberships:
            acc = mem.account
            prof = acc.profile
            accounts_out.append({
                "subs_account_id": acc.id,
                "dashboard_account_id": acc.mirror_dashboard_id,
                "username": acc.username,
                "platform": acc.platform,
                "profile_name": prof.name if prof else None,
                "last_synced_at": (
                    mem.last_synced_at.isoformat() if mem.last_synced_at else None
                ),
            })
        pres = presumed_csv_fields(
            username=member.username,
            display_name=member.display_name or "",
            bio=member.bio or "",
            platform=member.platform,
        )
        presumed_rows = [{"label": h, "value": pres[h]} for h in CSV_PRESUMED_HEADERS]
        return Response({
            "id": member.id,
            "platform": member.platform,
            "username": member.username,
            "external_id": member.external_id or "",
            "display_name": member.display_name or "",
            "avatar_url": member.avatar_url or "",
            "bio": member.bio or "",
            "is_private": bool(member.is_private),
            "follower_count": int(member.follower_count or 0),
            "following_count": int(member.following_count or 0),
            "like_count": int(member.like_count or 0),
            "follows_tracked_accounts": int(member.follows_tracked_accounts or 0),
            "created_at": member.created_at.isoformat() if member.created_at else None,
            "updated_at": member.updated_at.isoformat() if member.updated_at else None,
            "tracked_accounts": accounts_out,
            "presumed": presumed_rows,
        })

    dashboard_errors: list[str] = []
    for mem in memberships:
        acc = mem.account
        if not acc.mirror_dashboard_id:
            continue
        try:
            dashboard_delete_audience_member_by_username(
                int(acc.mirror_dashboard_id),
                member.username,
            )
        except Exception as exc:
            dashboard_errors.append(f"@{acc.username}: {exc}")

    AccountAudienceMembership.objects.filter(
        member=member,
        account_id__in=visible_ids,
    ).delete()

    if not member.memberships.exists():
        member.delete()

    body: dict = {"ok": True, "removed_memberships": len(memberships)}
    if dashboard_errors:
        body["dashboard_errors"] = dashboard_errors
    return Response(body, status=status.HTTP_200_OK)


@api_view(["GET"])
def profiles_list(_request):
    """Профили в БД subs (для фильтра на фронте)."""
    rows = Profile.objects.order_by("name")
    return Response([{"id": p.id, "name": p.name} for p in rows])


@api_view(["POST"])
def sync_dashboard(_request):
    """Подтянуть профили и отслеживаемые аккаунты выбранных площадок с дашборда."""
    try:
        stats = sync_profiles_and_accounts()
        return Response({"ok": True, **stats})
    except Exception as exc:
        return Response(
            {"detail": f"Ошибка синхронизации: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def sync_audience_stop(_request):
    """
    Остановить текущий съём аудитории на дашборде (Playwright).
    Используется при «Остановить» в массовом или одиночном сборе подписчиков в subs.
    """
    try:
        dashboard_stop_audience_scrape()
        return Response({"ok": True, "stopped": True})
    except Exception as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def sync_account_audience(request, pk: int):
    """
    Съём на дашборде + импорт списка аудитории в subs для аккаунта с id в БД subs.
    После полного импорта удаляются связи с подписчиками, которых больше нет в ответе дашборда (отписки).
    Тело:
    - audience_mode: list | enrich | full (по умолчанию list в subs UI);
    - skip_existing_member_profiles: при full — не открывать профили уже известных подписчиков.
    - enrich_usernames: при enrich — обновить только указанные ники (массив строк).
    """
    try:
        acc = Account.objects.get(pk=int(pk))
    except (Account.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "Аккаунт не найден"}, status=status.HTTP_404_NOT_FOUND)
    if not acc.mirror_dashboard_id:
        return Response(
            {"detail": "Нет mirror_dashboard_id — выполните POST /api/subscribers/sync/dashboard/"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    dash_body: dict = {"audience_mode": "list"}
    if isinstance(getattr(request, "data", None), dict):
        raw_mode = request.data.get("audience_mode")
        if raw_mode is not None:
            dash_body["audience_mode"] = str(raw_mode).strip().lower()
        if bool(request.data.get("skip_existing_member_profiles")):
            dash_body["skip_existing_member_profiles"] = True
        raw_enrich = request.data.get("enrich_usernames")
        if raw_enrich is not None:
            if not isinstance(raw_enrich, list):
                return Response(
                    {"detail": "enrich_usernames должен быть массивом ников."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            names = [
                str(x or "").strip().lstrip("@").lower()
                for x in raw_enrich
                if str(x or "").strip()
            ]
            if names:
                dash_body["enrich_usernames"] = names
    try:
        dash_result = dashboard_refresh_account(int(acc.mirror_dashboard_id), body=dash_body)
        n, pruned = import_audience_into_subs(acc)
        enriched_members: list = []
        enriched_ok_count = 0
        enriched_weak_count = 0
        if isinstance(dash_result, dict):
            raw_em = dash_result.get("enriched_members")
            if isinstance(raw_em, list):
                enriched_members = raw_em
            enriched_ok_count = int(dash_result.get("enriched_ok_count") or 0)
            enriched_weak_count = int(dash_result.get("enriched_weak_count") or 0)
        return Response({
            "ok": True,
            "imported": n,
            "pruned_memberships": pruned,
            "audience_mode": dash_body.get("audience_mode"),
            "enriched_members": enriched_members,
            "enriched_ok_count": enriched_ok_count,
            "enriched_weak_count": enriched_weak_count,
            "dashboard": dash_result,
        })
    except Exception as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
