"""Локальное хранение превью постов + fallback на thumbnail_url."""

from __future__ import annotations

import logging
import re

from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse

from .media_fetch import ext_from_content_type, fetch_image_bytes, referer_for_image_url
from .models import Account, Platform, Post

logger = logging.getLogger(__name__)


def post_has_stored_thumbnail(post: Post) -> bool:
    name = (post.thumbnail_file.name or "").strip()
    if not name:
        return False
    try:
        return post.thumbnail_file.storage.exists(name)
    except Exception:
        return False


def _content_type_from_filename(name: str) -> str:
    low = (name or "").lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith(".avif"):
        return "image/avif"
    return "image/jpeg"


def try_download_and_store(post: Post, url: str, *, platform: str) -> bool:
    """Скачать превью в thumbnail_file. thumbnail_url не меняем."""
    url = (url or "").strip()
    if not url:
        return False
    fetched = fetch_image_bytes(url, referer_for_image_url(platform, url))
    if not fetched:
        return False
    data, content_type = fetched
    ext = ext_from_content_type(content_type)
    safe_ext = re.sub(r"[^\w\-.]+", "_", str(post.external_id or "post"))[:48]
    filename = f"{post.pk}_{platform}_{safe_ext}{ext}"
    if post.thumbnail_file:
        try:
            post.thumbnail_file.delete(save=False)
        except Exception:
            pass
    post.thumbnail_file.save(filename, ContentFile(data), save=True)
    return True


def ensure_post_thumbnail_after_sync(
    post: Post,
    account: Account,
    *,
    scrape_included_thumbnail: bool,
    scraped_thumbnail_url: str | None,
) -> None:
    """
    После sync постов: скачать превью один раз, если файла ещё нет.
    thumbnail_missing — в съёме нет превью; при автообновлении не повторяем.
    """
    if post_has_stored_thumbnail(post):
        return
    if post.thumbnail_missing:
        return
    if not scrape_included_thumbnail:
        return

    url = (scraped_thumbnail_url or "").strip()
    if not url:
        if not post.thumbnail_missing:
            Post.objects.filter(pk=post.pk).update(thumbnail_missing=True)
        return

    source = (post.thumbnail_url or url).strip()
    if not source:
        return
    if try_download_and_store(post, source, platform=account.platform):
        Post.objects.filter(pk=post.pk).update(thumbnail_missing=False)


def _proxy_thumbnail_from_url(account: Account, url: str) -> HttpResponse | None:
    fetched = fetch_image_bytes(url, referer_for_image_url(account.platform, url))
    if not fetched:
        return None
    data, content_type = fetched
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "max-age=7200, public"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def serve_post_thumbnail_response(pk: int) -> HttpResponse:
    """GET /api/posts/<pk>/thumbnail/ — файл, иначе прокси thumbnail_url."""
    try:
        post = Post.objects.select_related("account").get(pk=pk)
    except Post.DoesNotExist:
        return HttpResponse(status=404)

    account = post.account

    if post_has_stored_thumbnail(post):
        name = post.thumbnail_file.name or ""
        response = FileResponse(
            post.thumbnail_file.open("rb"),
            content_type=_content_type_from_filename(name),
        )
        response["Cache-Control"] = "max-age=86400, public"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    if post.thumbnail_missing and not (post.thumbnail_url or "").strip():
        return HttpResponse(status=404)

    url = (post.thumbnail_url or "").strip()
    if not url:
        return HttpResponse(status=404)

    proxied = _proxy_thumbnail_from_url(account, url)
    if proxied:
        return proxied
    return HttpResponse(status=404)
