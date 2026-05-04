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

from .models import Platform, Post, PostSnapshot


# ── constants ────────────────────────────────────────────────────────────────

PERIOD_DAYS: dict[str, int | None] = {"1d": 1, "7d": 7, "30d": 30, "all": None}

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


def _annotated_qs(account_id=None, platform=None, period="1d", min_views=MIN_VIEWS_DEFAULT):
    today = timezone.now().date()
    qs = Post.objects.select_related("account").filter(view_count__gte=min_views)

    if account_id:
        qs = qs.filter(account_id=account_id)
    if platform:
        qs = qs.filter(account__platform=platform)

    days = PERIOD_DAYS.get(period)
    if days is not None:
        period_start = today - datetime.timedelta(days=days)
        qs = qs.annotate(
            view_delta_period=ExpressionWrapper(
                F("view_count") - _snap_subq("view_count", period_start),
                output_field=IntegerField(),
            ),
            like_delta_period=ExpressionWrapper(
                F("like_count") - _snap_subq("like_count", period_start),
                output_field=IntegerField(),
            ),
        )
    else:
        qs = qs.annotate(
            view_delta_period=F("view_count"),
            like_delta_period=F("like_count"),
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
    min_views = int(request.query_params.get("min_views", MIN_VIEWS_DEFAULT))
    hashtag   = request.query_params.get("hashtag") or None
    page      = max(1, int(request.query_params.get("page", 1)))
    page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))

    qs = _annotated_qs(
        account_id=account_id, platform=platform, period=period, min_views=min_views
    )
    if hashtag:
        qs = qs.filter(hashtags__contains=[hashtag])
    qs = qs.order_by(_sort_expr(sort_by))

    total = qs.count()
    posts = qs[(page - 1) * page_size: page * page_size]

    return Response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "items": [_post_dict(p) for p in posts],
    })


@api_view(["GET"])
def insights(request):
    """Platform comparison, top hashtags, and best posting times."""
    period     = request.query_params.get("period", "1d")
    platform   = request.query_params.get("platform") or None
    account_id = request.query_params.get("account_id") or None
    min_views  = int(request.query_params.get("min_views", MIN_VIEWS_DEFAULT))

    qs = _annotated_qs(
        account_id=account_id, platform=platform, period=period, min_views=min_views
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
