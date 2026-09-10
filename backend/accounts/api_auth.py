"""Bearer-аутентификация внешних API-ключей (/api/v1/)."""
from __future__ import annotations

import hashlib
import secrets
from typing import Iterable

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from .models import ExternalApiKey

KEY_PREFIX = "ads_"


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Возвращает (raw, prefix, hash). raw показывается один раз."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw[:12]
    return raw, prefix, hash_api_key(raw)


class BearerApiKeyAuthentication(authentication.BaseAuthentication):
    """Authorization: Bearer ads_…"""

    keyword = "Bearer"

    def authenticate_header(self, request):
        # Без этого DRF отвечает 403 вместо 401 при ошибке аутентификации.
        return self.keyword

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header:
            raise exceptions.AuthenticationFailed("Требуется Authorization: Bearer <api_key>.")
        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise exceptions.AuthenticationFailed(
                "Ожидается заголовок Authorization: Bearer <api_key>."
            )
        raw = parts[1].strip()
        if not raw:
            raise exceptions.AuthenticationFailed("Пустой API-ключ.")
        key = ExternalApiKey.objects.select_related("domain").filter(
            key_hash=hash_api_key(raw),
            is_active=True,
        ).first()
        if key is None:
            raise exceptions.AuthenticationFailed("Неверный или отозванный API-ключ.")
        ExternalApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        # Домен из ключа жёстко задаёт арендатора (перекрывает X-Domain от клиента).
        if key.domain_id and key.domain and key.domain.is_active:
            request.META["HTTP_X_DOMAIN"] = key.domain.slug
        request.api_key = key
        return (None, key)


class RequireScopes(permissions.BasePermission):
    """Проверка scopes у ExternalApiKey. Задаётся через view.required_scopes."""

    message = "Недостаточно прав у API-ключа."

    def has_permission(self, request, view) -> bool:
        key = getattr(request, "auth", None)
        if not isinstance(key, ExternalApiKey):
            raise exceptions.NotAuthenticated("Требуется Authorization: Bearer <api_key>.")
        needed: Iterable[str] = getattr(view, "required_scopes", ()) or ()
        if not needed:
            return True
        missing = [s for s in needed if not key.has_scope(s)]
        if missing:
            self.message = f"Ключу нужны права: {', '.join(missing)}."
            return False
        return True


class RequireActionScopes(permissions.BasePermission):
    """Для ViewSet: view.action_scopes = {'list': ('read',), 'create': ('write',), ...}."""

    message = "Недостаточно прав у API-ключа."

    def has_permission(self, request, view) -> bool:
        key = getattr(request, "auth", None)
        if not isinstance(key, ExternalApiKey):
            raise exceptions.NotAuthenticated("Требуется Authorization: Bearer <api_key>.")
        action = getattr(view, "action", None) or ""
        mapping = getattr(view, "action_scopes", {}) or {}
        needed = mapping.get(action)
        if needed is None:
            self.message = f"Действие «{action}» недоступно во внешнем API."
            return False
        missing = [s for s in needed if not key.has_scope(s)]
        if missing:
            self.message = f"Ключу нужны права: {', '.join(missing)}."
            return False
        return True
