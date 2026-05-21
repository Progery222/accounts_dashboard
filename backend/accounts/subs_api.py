"""HTTP API только для клиента subs (не используется UI AccountsStats)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Account, Platform


@api_view(["POST"])
def subs_tiktok_audience_bulk(request):
    if (request.headers.get("X-Subs-Client") or "").strip() != "1":
        return Response(
            {"detail": "Требуется заголовок X-Subs-Client: 1"},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = getattr(request, "data", None)
    if not isinstance(body, dict):
        return Response({"detail": "Ожидается JSON-тело"}, status=status.HTTP_400_BAD_REQUEST)

    raw_ids = body.get("dashboard_account_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return Response(
            {"detail": "dashboard_account_ids — непустой массив id accounts.Account"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        dash_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return Response(
            {"detail": "Некорректные dashboard_account_ids"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    accounts = list(
        Account.objects.filter(pk__in=dash_ids, platform=Platform.TIKTOK).order_by("username"),
    )
    if not accounts:
        return Response(
            {"detail": "Нет TikTok-аккаунтов с указанными id"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from .audience import normalize_audience_mode
    from .subs_audience import refresh_tiktok_bulk_subs

    mode = "enrich"
    if body.get("audience_mode") is not None:
        try:
            mode = normalize_audience_mode(body.get("audience_mode"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    skip = bool(body.get("skip_existing_member_profiles"))
    enrich_map: dict[int, list[str] | None] | None = None
    raw_enrich = body.get("enrich_by_account")
    if isinstance(raw_enrich, dict):
        enrich_map = {}
        for k, v in raw_enrich.items():
            try:
                aid = int(k)
            except (TypeError, ValueError):
                continue
            if v is None:
                enrich_map[aid] = None
            elif isinstance(v, list):
                enrich_map[aid] = [
                    str(x or "").strip().lstrip("@").lower()
                    for x in v
                    if str(x or "").strip()
                ]

    try:
        result = refresh_tiktok_bulk_subs(
            accounts,
            audience_mode=mode,
            skip_existing_member_profiles=skip,
            enrich_by_dashboard_id=enrich_map,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response(
            {"detail": f"Ошибка bulk TikTok: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(result)
