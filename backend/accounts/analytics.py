"""
Analytics views: top posts, platform comparison, hashtag stats, best posting times.
"""
import datetime
from collections import defaultdict

from django.utils import timezone
from django.db.models import (
    ExpressionWrapper, F, FloatField, IntegerField,
    OuterRef, Subquery, Value, Case, When,
)

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import domains
from .models import Account, AccountSnapshot, AutoRefreshPoint, Platform, Post, PostSnapshot, Topic


# ── constants ────────────────────────────────────────────────────────────────

PERIOD_DAYS: dict[str, int] = {"all": 0, "1d": 1, "7d": 7, "30d": 30}

WEEKDAY_LABELS = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}

MIN_VIEWS_DEFAULT = 10


# ── helpers ──────────────────────────────────────────────────────────────────

def _snap_subq(field: str, period_start) -> Subquery:
    """Return the most recent snapshot value for `field` on or before period_start.

    Returns NULL (not 0) when no snapshot exists so that the computed delta is
    also NULL — matching the account-level delta behaviour where missing history
    yields None rather than showing the full counter as a single-day gain.
    """
    return Subquery(
        PostSnapshot.objects.filter(
            post=OuterRef("pk"),
            date__lte=period_start,
        ).order_by("-date").values(field)[:1],
        output_field=IntegerField(),
    )


def _snap_subq_earliest(field: str) -> Subquery:
    """Самый ранний снимок поста — опора для периода All."""
    return Subquery(
        PostSnapshot.objects.filter(post=OuterRef("pk"))
        .order_by("date")
        .values(field)[:1],
        output_field=IntegerField(),
    )


def _normalize_scrape_filter(raw: str | None) -> str:
    v = (raw or "active").strip().lower()
    if v in ("missing", "not_found", "scrape_not_found", "possibly_deleted"):
        return "missing"
    if v in ("all", "include_missing"):
        return "all"
    return "active"


def _scope_ids(request):
    """Аккаунты, которыми ограничена аналитика.

    Домен из X-Domain сужает выборку как и везде (на «Стендах» — аккаунты
    всех стендов ветки). Параметр ``topic`` — один стенд/тема этой ветки.
    Вернёт ``(scope, ids)``: ids — None, если по стенду не сужаем.
    """
    scope = domains.resolve(request)
    raw = (request.query_params.get("topic") or "").strip()
    if not raw or raw == "all" or not domains.is_topics(scope):
        return scope, None
    try:
        topic = Topic.objects.filter(pk=int(raw), board=scope.domain.slug).first()
    except (TypeError, ValueError):
        topic = None
    if topic is None:
        return scope, []
    return scope, list(topic.accounts.values_list("id", flat=True))


def _annotated_qs(
    account_id=None,
    platform=None,
    profile_id=None,
    owner_id=None,
    period="1d",
    min_views=MIN_VIEWS_DEFAULT,
    scrape_filter: str = "active",
    scope=None,
    account_ids=None,
):
    today = timezone.now().date()
    scrape_filter = _normalize_scrape_filter(scrape_filter)
    qs = domains.narrow(Post.objects.select_related("account"), scope, field="account__domain")
    if account_ids is not None:
        qs = qs.filter(account_id__in=account_ids)
    if scrape_filter == "missing":
        qs = qs.filter(missing_from_scrape_at__isnull=False)
    elif scrape_filter == "active":
        qs = qs.filter(missing_from_scrape_at__isnull=True)
    if min_views > 0:
        qs = qs.filter(view_count__gte=min_views)

    if account_id:
        qs = qs.filter(account_id=account_id)
    if platform:
        qs = qs.filter(account__platform=platform)
    if profile_id == "none":
        qs = qs.filter(account__profile__isnull=True)
    elif profile_id:
        try:
            qs = qs.filter(account__profile_id=int(profile_id))
        except (TypeError, ValueError):
            pass
    if owner_id == "none":
        qs = qs.filter(account__owner__isnull=True)
    elif owner_id:
        try:
            qs = qs.filter(account__owner_id=int(owner_id))
        except (TypeError, ValueError):
            pass

    days = PERIOD_DAYS.get(period, 7)
    if days == 0:
        view_snap = _snap_subq_earliest("view_count")
        like_snap = _snap_subq_earliest("like_count")
    else:
        period_start = today - datetime.timedelta(days=days)
        view_snap = _snap_subq("view_count", period_start)
        like_snap = _snap_subq("like_count", period_start)
    qs = qs.annotate(
        view_delta_period=ExpressionWrapper(
            F("view_count") - view_snap,
            output_field=IntegerField(),
        ),
        like_delta_period=ExpressionWrapper(
            F("like_count") - like_snap,
            output_field=IntegerField(),
        ),
    )

    qs = qs.annotate(
        engagement_rate=Case(
            When(
                view_count__gt=0,
                then=ExpressionWrapper(
                    (F("like_count") + F("comment_count") + F("share_count"))
                    * 100.0
                    / F("view_count"),
                    output_field=FloatField(),
                ),
            ),
            default=Value(0.0, output_field=FloatField()),
        )
    )
    return qs


def _post_dict(p) -> dict:
    return {
        "id": p.id,
        "external_id": p.external_id,
        "description": p.description[:200],
        "hashtags": p.hashtags,
        "thumbnail_url": p.thumbnail_url,
        "thumbnail_missing": bool(p.thumbnail_missing),
        "post_url": p.post_url,
        "posted_at": p.posted_at,
        "account": {
            "id": p.account_id,
            "username": p.account.username,
            "platform": p.account.platform,
            "platform_label": p.account.get_platform_display(),
            "display_name": p.account.display_name,
            "avatar_url": p.account.avatar_url,
        },
        "view_count": p.view_count,
        "like_count": p.like_count,
        "comment_count": p.comment_count,
        "share_count": p.share_count,
        "engagement_rate": round(float(p.engagement_rate), 2),
        "view_delta": p.view_delta_period,
        "like_delta": p.like_delta_period,
        "missing_from_scrape_at": p.missing_from_scrape_at,
        "scrape_not_found": p.missing_from_scrape_at is not None,
    }


# ── views ────────────────────────────────────────────────────────────────────

def _sort_expr(sort_by: str):
    """Return an ORDER BY expression with NULLs sorted last."""
    field_map = {
        "views":      F("view_count"),
        "likes":      F("like_count"),
        "comments":   F("comment_count"),
        "shares":     F("share_count"),
        "er":         F("engagement_rate"),
        "view_delta": F("view_delta_period"),
        "like_delta": F("like_delta_period"),
    }
    field = field_map.get(sort_by, F("view_count"))
    return field.desc(nulls_last=True)


@api_view(["GET"])
def top_posts(request):
    """Paginated top posts with sortable metrics and period deltas."""
    period    = request.query_params.get("period", "1d")
    sort_by   = request.query_params.get("sort_by", "view_delta")
    platform  = request.query_params.get("platform") or None
    account_id = request.query_params.get("account_id") or None
    profile_id = request.query_params.get("profile_id") or None
    owner_id = request.query_params.get("owner_id") or None
    min_views = int(request.query_params.get("min_views", MIN_VIEWS_DEFAULT))
    hashtag   = request.query_params.get("hashtag") or None
    page      = max(1, int(request.query_params.get("page", 1)))
    page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))

    scrape_filter = _normalize_scrape_filter(request.query_params.get("scrape_filter"))
    scope, topic_ids = _scope_ids(request)
    qs = _annotated_qs(
        account_id=account_id,
        platform=platform,
        profile_id=profile_id,
        owner_id=owner_id,
        period=period,
        min_views=min_views,
        scrape_filter=scrape_filter,
        scope=scope,
        account_ids=topic_ids,
    )
    if hashtag:
        qs = qs.filter(hashtags__contains=[hashtag])
    if scrape_filter == "missing":
        qs = qs.order_by("-missing_from_scrape_at", "-id")
    else:
        qs = qs.order_by(_sort_expr(sort_by))

    total = qs.count()
    posts = qs[(page - 1) * page_size: page * page_size]

    return Response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "scrape_filter": scrape_filter,
        "items": [_post_dict(p) for p in posts],
    })


@api_view(["GET"])
def insights(request):
    """Platform comparison, top hashtags, and best posting times."""
    period     = request.query_params.get("period", "1d")
    platform   = request.query_params.get("platform") or None
    account_id = request.query_params.get("account_id") or None
    profile_id = request.query_params.get("profile_id") or None
    owner_id = request.query_params.get("owner_id") or None
    min_views  = int(request.query_params.get("min_views", MIN_VIEWS_DEFAULT))

    scrape_filter = _normalize_scrape_filter(request.query_params.get("scrape_filter"))
    scope, topic_ids = _scope_ids(request)
    qs = _annotated_qs(
        account_id=account_id,
        platform=platform,
        profile_id=profile_id,
        owner_id=owner_id,
        period=period,
        min_views=min_views,
        scrape_filter=scrape_filter,
        scope=scope,
        account_ids=topic_ids,
    )

    # Fetch all posts needed for Python-level aggregation
    rows = list(qs.values(
        "view_count", "like_count", "comment_count", "share_count",
        "engagement_rate", "hashtags", "posted_at", "account__platform",
        # keep like_count available for hashtag avg_likes aggregation
    ))

    platform_labels = dict(Platform.choices)

    # ── Platform comparison ──────────────────────────────────────────────────
    pl_data: dict[str, dict] = defaultdict(
        lambda: {"post_count": 0, "total_views": 0, "total_likes": 0, "total_er": 0.0}
    )
    for r in rows:
        pl = r["account__platform"]
        pl_data[pl]["post_count"]   += 1
        pl_data[pl]["total_views"]  += r["view_count"]
        pl_data[pl]["total_likes"]  += r["like_count"]
        pl_data[pl]["total_er"]     += float(r["engagement_rate"] or 0)

    platform_comparison = []
    for pl, s in pl_data.items():
        n = s["post_count"]
        platform_comparison.append({
            "platform":       pl,
            "platform_label": platform_labels.get(pl, pl),
            "post_count":     n,
            "avg_views":      round(s["total_views"] / n) if n else 0,
            "avg_likes":      round(s["total_likes"] / n) if n else 0,
            "avg_er":         round(s["total_er"] / n, 2) if n else 0.0,
        })
    platform_comparison.sort(key=lambda x: -x["avg_views"])

    # ── Top hashtags ─────────────────────────────────────────────────────────
    tag_stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "total_views": 0, "total_likes": 0, "total_er": 0.0}
    )
    for r in rows:
        for tag in (r["hashtags"] or []):
            tag_stats[tag]["count"]       += 1
            tag_stats[tag]["total_views"] += r["view_count"]
            tag_stats[tag]["total_likes"] += r["like_count"]
            tag_stats[tag]["total_er"]    += float(r["engagement_rate"] or 0)

    top_hashtags = []
    for tag, s in tag_stats.items():
        n = s["count"]
        top_hashtags.append({
            "tag":        tag,
            "count":      n,
            "avg_views":  round(s["total_views"] / n) if n else 0,
            "avg_likes":  round(s["total_likes"] / n) if n else 0,
            "avg_er":     round(s["total_er"] / n, 2) if n else 0.0,
        })
    top_hashtags.sort(key=lambda x: -x["count"])
    top_hashtags = top_hashtags[:200]

    # ── Best time to post ────────────────────────────────────────────────────
    hour_stats:    dict[int, dict] = defaultdict(lambda: {"count": 0, "total_views": 0, "total_er": 0.0})
    weekday_stats: dict[int, dict] = defaultdict(lambda: {"count": 0, "total_views": 0, "total_er": 0.0})

    for r in rows:
        dt = r["posted_at"]
        if not dt:
            continue
        if not hasattr(dt, "hour"):
            try:
                dt = datetime.datetime.fromisoformat(str(dt))
            except Exception:
                continue
        try:
            # Нормализуем в локальную TZ проекта (Europe/Moscow), чтобы график
            # "Лучшее время" соответствовал подписи UI.
            if timezone.is_aware(dt):
                dt = timezone.localtime(dt, timezone.get_current_timezone())
        except Exception:
            pass
        h  = dt.hour
        wd = dt.isoweekday()   # 1=Mon … 7=Sun
        er = float(r["engagement_rate"] or 0)
        v  = r["view_count"]

        hour_stats[h]["count"]       += 1
        hour_stats[h]["total_views"] += v
        hour_stats[h]["total_er"]    += er

        weekday_stats[wd]["count"]       += 1
        weekday_stats[wd]["total_views"] += v
        weekday_stats[wd]["total_er"]    += er

    best_hours = []
    for h in range(24):
        s = hour_stats[h]
        n = s["count"]
        best_hours.append({
            "hour":       h,
            "post_count": n,
            "avg_views":  round(s["total_views"] / n) if n else 0,
            "avg_er":     round(s["total_er"] / n, 2) if n else 0.0,
        })

    best_weekdays = []
    for wd in range(1, 8):
        s = weekday_stats[wd]
        n = s["count"]
        best_weekdays.append({
            "weekday":       wd,
            "weekday_label": WEEKDAY_LABELS[wd],
            "post_count":    n,
            "avg_views":     round(s["total_views"] / n) if n else 0,
            "avg_er":        round(s["total_er"] / n, 2) if n else 0.0,
        })

    return Response({
        "platform_comparison": platform_comparison,
        "top_hashtags":        top_hashtags,
        "best_hours":          best_hours,
        "best_weekdays":       best_weekdays,
    })


# ── Ряд показателя по набору аккаунтов (поп-ап карточек сводки) ─────────────

SERIES_METRICS = {
    "followers": "follower_count",
    "views": "view_count",
    "likes": "like_count",
    "posts": "post_count",
}
SERIES_PERIOD_DAYS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "all": None}
SERIES_MAX_IDS = 5000


def _series_daily(ids: list[int], field: str, days, today) -> list[dict]:
    """Сумма показателя по дням из суточных снимков, сегодня — текущие цифры.

    Снимок за день D держит последнее значение дня D. Если у аккаунта за день
    снимка нет, берём предыдущий известный; до первого снимка — первый
    известный: аккаунт существовал и раньше, просто мы его ещё не считали.
    Без этого добавление аккаунта на стенд рисовало бы ступеньку роста.
    """
    current = dict(Account.objects.filter(id__in=ids).values_list("id", field))
    snaps = AccountSnapshot.objects.filter(account_id__in=ids, date__lt=today)
    if days is None:
        first = snaps.order_by("date").values_list("date", flat=True).first()
        start = first or today
    else:
        start = today - datetime.timedelta(days=days)
    rows = snaps.filter(date__gte=start).values_list("account_id", "date", field)
    by_acc: dict[int, dict] = defaultdict(dict)
    for acc_id, d, v in rows:
        by_acc[acc_id][d] = int(v or 0)
    # Последний снимок до начала окна — стартовое значение.
    base = dict(
        Account.objects.filter(id__in=ids).annotate(
            b=Subquery(
                AccountSnapshot.objects.filter(account_id=OuterRef("pk"), date__lt=start)
                .order_by("-date").values(field)[:1]
            )
        ).values_list("id", "b")
    )
    dates = [start + datetime.timedelta(days=i) for i in range((today - start).days)]
    totals = [0] * len(dates)
    for acc_id in ids:
        if acc_id not in current:
            continue
        own = by_acc.get(acc_id, {})
        first_known = base.get(acc_id)
        if first_known is None:
            first_known = own[min(own)] if own else int(current[acc_id] or 0)
        last = first_known
        for i, d in enumerate(dates):
            if d in own:
                last = own[d]
            totals[i] += last
    points = [{"t": d.isoformat(), "v": v} for d, v in zip(dates, totals)]
    points.append({"t": timezone.now().isoformat(), "v": sum(int(current[i] or 0) for i in ids if i in current)})
    return points


def _series_views_24h(ids: list[int], now) -> list[dict]:
    """Просмотры за последние сутки по точкам автообновления (разбивка до аккаунта)."""
    since = now - datetime.timedelta(hours=24)
    current = dict(Account.objects.filter(id__in=ids).values_list("id", "view_count"))
    yesterday = timezone.localdate() - datetime.timedelta(days=1)
    known = dict(
        AccountSnapshot.objects.filter(account_id__in=ids, date=yesterday).values_list("account_id", "view_count")
    )
    pts = list(
        AutoRefreshPoint.objects.filter(measured_at__gte=since, measured_at__lte=now)
        .exclude(account_totals={}).order_by("measured_at").values_list("measured_at", "account_totals")
    )
    if not pts:
        return []
    keys = [str(i) for i in ids if i in current]
    last = {k: int(known.get(int(k), current[int(k)]) or 0) for k in keys}
    out = [{"t": since.isoformat(), "v": sum(last.values())}]
    for ts, totals in pts:
        totals = totals or {}
        for k in keys:
            if k in totals:
                last[k] = int(totals[k] or 0)
        out.append({"t": ts.isoformat(), "v": sum(last.values())})
    out.append({"t": now.isoformat(), "v": sum(int(current[int(k)] or 0) for k in keys)})
    return out


@api_view(["POST"])
def series(request):
    """Как менялся показатель у набора аккаунтов: {"account_ids", "metric", "period"}.

    metric — followers / views / likes / posts; period — 1d / 7d / 30d / 90d / all.
    Ответ: {"points": [{"t", "v"}...], "first", "last", "delta"} — сумма по
    аккаунтам. Аккаунты передаёт фронт: те же, что дали цифру на карточке
    (стенд, площадки и поиск), поэтому график сходится с карточкой.
    """
    metric = str(request.data.get("metric") or "views")
    period = str(request.data.get("period") or "7d")
    if metric not in SERIES_METRICS:
        return Response({"detail": "metric: followers, views, likes или posts"}, status=400)
    if period not in SERIES_PERIOD_DAYS:
        return Response({"detail": "period: 1d, 7d, 30d, 90d или all"}, status=400)
    raw = request.data.get("account_ids")
    if not isinstance(raw, list):
        return Response({"detail": "account_ids должен быть списком"}, status=400)
    if len(raw) > SERIES_MAX_IDS:
        return Response({"detail": "Слишком много аккаунтов"}, status=400)
    try:
        ids = sorted({int(x) for x in raw})
    except (TypeError, ValueError):
        return Response({"detail": "account_ids: только числа"}, status=400)
    field = SERIES_METRICS[metric]
    now = timezone.now()
    today = timezone.localdate()
    points: list[dict] = []
    granularity = "day"
    if ids:
        if period == "1d" and metric == "views":
            points = _series_views_24h(ids, now)
            granularity = "point"
        if not points:
            points = _series_daily(ids, field, SERIES_PERIOD_DAYS[period], today)
    first = points[0]["v"] if points else 0
    last = points[-1]["v"] if points else 0
    return Response({
        "metric": metric,
        "period": period,
        "granularity": granularity,
        "points": points,
        "first": first,
        "last": last,
        "delta": last - first,
    })
