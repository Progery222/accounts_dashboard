"""Локальное хранение аватаров аккаунтов + fallback на avatar_url (CDN-прокси)."""

from __future__ import annotations

import logging
import re

import httpx
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse

from .media_fetch import (
    MEDIA_UA,
    ext_from_content_type,
    fetch_image_bytes,
    platform_referer,
    referer_for_image_url,
)
from .models import Account, Platform

logger = logging.getLogger(__name__)


def account_has_stored_avatar(account: Account) -> bool:
    name = (account.avatar_file.name or "").strip()
    if not name:
        return False
    try:
        return account.avatar_file.storage.exists(name)
    except Exception:
        return False


def fetch_avatar_bytes(url: str, referer: str) -> tuple[bytes, str] | None:
    return fetch_image_bytes(url, referer)


def _refresh_avatar_url_from_profile(account: Account) -> str:
    """Свежий URL со страницы профиля (протухший CDN в avatar_url)."""
    if account.platform == Platform.TIKTOK:
        try:
            from platforms.tiktok.service import _extract_avatar_from_html

            profile_url = f"https://www.tiktok.com/@{account.username}"
            r_prof = httpx.get(
                profile_url,
                headers={
                    "User-Agent": MEDIA_UA,
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    ),
                },
                follow_redirects=True,
                timeout=15.0,
            )
            if r_prof.status_code == 200 and r_prof.text:
                return _extract_avatar_from_html(r_prof.text) or ""
        except Exception:
            pass
        return ""

    if account.platform == Platform.INSTAGRAM:
        try:
            profile_url = f"https://www.instagram.com/{account.username}/"
            r_prof = httpx.get(
                profile_url,
                headers={"User-Agent": MEDIA_UA, "Accept-Language": "ru-RU,ru;q=0.9"},
                follow_redirects=True,
                timeout=15.0,
            )
            if r_prof.status_code != 200 or not r_prof.text:
                return ""
            html = r_prof.text
            og_image = re.search(
                r'<meta\s+property="og:image"\s+content="([^"]+)"',
                html,
                re.I,
            )
            if og_image:
                return og_image.group(1)
            for pat in (
                r'"profile_pic_url_hd"\s*:\s*"(https?://[^"\\]+)"',
                r'"profile_pic_url"\s*:\s*"(https?://[^"\\]+)"',
            ):
                m = re.search(pat, html)
                if m:
                    return m.group(1).replace("\\u0026", "&").replace("\\/", "/")
        except Exception:
            pass
        return ""

    if account.platform == Platform.THREADS:
        try:
            profile_url = f"https://www.threads.net/@{account.username}"
            r_prof = httpx.get(
                profile_url,
                headers={"User-Agent": MEDIA_UA},
                follow_redirects=True,
                timeout=15.0,
            )
            if r_prof.status_code != 200 or not r_prof.text:
                return ""
            html = r_prof.text
            og_image = re.search(
                r'<meta\s+property="og:image"\s+content="([^"]+)"',
                html,
                re.I,
            )
            if og_image:
                return og_image.group(1)
            for pat in (
                r'"profile_pic_url"\s*:\s*"(https?://[^"\\]+)"',
                r'"(https://scontent[^"\\]+)"',
            ):
                m = re.search(pat, html)
                if m and "cdninstagram" in m.group(1):
                    return m.group(1).replace("\\u0026", "&").replace("\\/", "/")
        except Exception:
            pass
        return ""

    return ""


def _proxy_avatar_from_url(account: Account, url: str) -> HttpResponse | None:
    referer = referer_for_image_url(account.platform, url)
    fetched = fetch_avatar_bytes(url, referer)
    if not fetched and account.platform in (
        Platform.TIKTOK,
        Platform.INSTAGRAM,
        Platform.THREADS,
    ):
        fresh = _refresh_avatar_url_from_profile(account)
        if fresh:
            fetched = fetch_avatar_bytes(fresh, referer_for_image_url(account.platform, fresh))
            if fetched and fresh != (account.avatar_url or "").strip():
                Account.objects.filter(pk=account.pk).update(avatar_url=fresh)
    if not fetched:
        return None
    data, content_type = fetched
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "max-age=7200, public"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def try_download_and_store(account: Account, url: str) -> bool:
    """Скачать по URL и сохранить в avatar_file. avatar_url не трогаем."""
    url = (url or "").strip()
    if not url:
        return False
    fetched = fetch_avatar_bytes(url, referer_for_image_url(account.platform, url))
    if not fetched:
        return False
    data, content_type = fetched
    ext = ext_from_content_type(content_type)
    safe_user = re.sub(r"[^\w\-.]+", "_", account.username or "user")[:40]
    filename = f"{account.pk}_{account.platform}_{safe_user}{ext}"
    if account.avatar_file:
        try:
            account.avatar_file.delete(save=False)
        except Exception:
            pass
    account.avatar_file.save(filename, ContentFile(data), save=True)
    return True


def ensure_account_avatar_after_refresh(
    account: Account,
    *,
    scrape_included_avatar: bool,
    scraped_avatar_url: str | None,
) -> None:
    """
    После refresh: один раз скачать аватар, если файла ещё нет.
    avatar_missing — площадка отдала пустой avatar_url; повторно не пробуем.
    """
    if not scrape_included_avatar:
        return

    url = (scraped_avatar_url or "").strip()
    if not url:
        # Apify/парсер не вернул картинку — не затираем уже сохранённый аватар.
        if account_has_stored_avatar(account) or (account.avatar_url or "").strip():
            return
        if not account.avatar_missing:
            Account.objects.filter(pk=account.pk).update(avatar_missing=True)
        return

    if account.avatar_missing:
        Account.objects.filter(pk=account.pk).update(avatar_missing=False)

    source = url
    if try_download_and_store(account, source):
        if source != (account.avatar_url or "").strip():
            Account.objects.filter(pk=account.pk).update(avatar_url=source)
        return

    if account_has_stored_avatar(account) or (account.avatar_url or "").strip():
        return

    if source != (account.avatar_url or "").strip():
        Account.objects.filter(pk=account.pk).update(avatar_url=source)


def serve_account_avatar_response(pk: int) -> HttpResponse:
    """GET /api/accounts/<pk>/avatar/ — файл, иначе прокси avatar_url."""
    try:
        account = Account.objects.get(pk=pk)
    except Account.DoesNotExist:
        return HttpResponse(status=404)

    if account_has_stored_avatar(account):
        content_type = "image/jpeg"
        name = account.avatar_file.name or ""
        if name.lower().endswith(".png"):
            content_type = "image/png"
        elif name.lower().endswith(".webp"):
            content_type = "image/webp"
        elif name.lower().endswith(".gif"):
            content_type = "image/gif"
        response = FileResponse(
            account.avatar_file.open("rb"),
            content_type=content_type,
        )
        response["Cache-Control"] = "max-age=86400, public"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    if account.avatar_missing and not (account.avatar_url or "").strip():
        return HttpResponse(status=404)

    url = (account.avatar_url or "").strip()
    if not url and account.platform == Platform.THREADS:
        first_post = account.posts.exclude(thumbnail_url="").order_by("-id").first()
        if first_post:
            url = (first_post.thumbnail_url or "").strip()

    if not url:
        return HttpResponse(status=404)

    proxied = _proxy_avatar_from_url(account, url)
    if proxied:
        return proxied
    return HttpResponse(status=404)
