"""Ограничение UI API по Origin (жёстче, чем «молчаливый» CORS браузера).

``/api/v1/`` и internal/healthz не трогаем: внешние сервисы ходят туда с Bearer
(часто без Origin или с чужого origin). UI-пути при ``Origin`` не из allowlist
получают 403.
"""
from __future__ import annotations

import re

from django.conf import settings
from django.http import JsonResponse


UI_API_PREFIXES = (
    "/api/accounts/",
    "/api/settings/",
    "/api/tiktok/",
    "/api/posts/",
)


def _compiled_origin_regexes() -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for raw in getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", []) or []:
        try:
            out.append(re.compile(raw))
        except re.error:
            continue
    return out


def origin_allowed(origin: str) -> bool:
    origin = (origin or "").strip()
    if not origin:
        return True
    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        return True
    allowed = getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []
    if origin in allowed:
        return True
    for rx in _compiled_origin_regexes():
        if rx.fullmatch(origin):
            return True
    return False


def _is_ui_api_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in UI_API_PREFIXES)


class UiApiOriginGateMiddleware:
    """Если браузер прислал Origin вне allowlist — режем UI API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/api/v1/") or path.startswith("/api/internal/") or path.startswith("/healthz"):
            return self.get_response(request)
        if not _is_ui_api_path(path):
            return self.get_response(request)

        origin = (request.headers.get("Origin") or "").strip()
        if origin and not origin_allowed(origin):
            return JsonResponse(
                {
                    "detail": (
                        "Origin не разрешён для UI API. "
                        "Внешним сервисам используйте /api/v1/ с Bearer-ключом."
                    ),
                },
                status=403,
            )
        return self.get_response(request)
