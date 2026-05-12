"""
Разбор ссылок Facebook для воркера: vanity (facebook.com/name) и числовые профили (profile.php?id=…).
"""
from __future__ import annotations

import re
from urllib.parse import unquote, parse_qs, urlparse


def normalize_facebook_profile_input(raw: str) -> tuple[str, str, str]:
    """
    Вернуть (nav_url_www, mbasic_timeline_url, post_url_prefix).

    nav_url_www — полный URL для первого перехода (www.facebook.com, без ``&sk=…``;
    второй переход на ``sk=reels_tab`` делает ``platforms/facebook/worker.py`` через ``page.goto``).
    mbasic_timeline_url — полный URL для fallback на mbasic.
    post_url_prefix — без завершающего слэша; fallback поста: ``{post_url_prefix}/posts/{id}``.
    """
    s = (raw or "").strip().lstrip("@").strip()
    if not s:
        raise ValueError("Пустой идентификатор Facebook")

    if not s.startswith(("http://", "https://")):
        if re.search(r"profile\.php", s, re.I) and re.search(r"\bid=", s, re.I):
            s = "https://www.facebook.com/" + s.lstrip("/")
        elif re.fullmatch(r"\d{6,24}", s):
            s = f"https://www.facebook.com/profile.php?id={s}"
        elif "/" not in s and "?" not in s and not s.startswith("."):
            s = f"https://www.facebook.com/{s}"
        else:
            s = "https://www.facebook.com/" + s.lstrip("/")

    u = urlparse(s)
    host = (u.netloc or "").lower()
    path = (u.path or "/").rstrip("/") or "/"
    if "facebook.com" not in host and host not in ("fb.com",):
        raise ValueError("Ссылка должна быть на домен Facebook (facebook.com)")

    path_last = path.rsplit("/", 1)[-1].lower()
    qs = parse_qs(u.query, keep_blank_values=True)

    if path_last == "profile.php":
        ids = qs.get("id") or []
        if not ids:
            raise ValueError("В ссылке profile.php не найден параметр id")
        pid = str(ids[0]).strip()
        if not re.fullmatch(r"\d{6,24}", pid):
            raise ValueError("Некорректный числовой id в profile.php")
        nav = f"https://www.facebook.com/profile.php?id={pid}"
        mbasic = f"https://mbasic.facebook.com/profile.php?id={pid}&v=timeline"
        post_base = f"https://www.facebook.com/{pid}"
        return nav, mbasic, post_base

    slug = path.strip("/").split("/")[0]
    if not slug or slug.lower() == "profile.php":
        raise ValueError("Не удалось извлечь имя страницы из URL Facebook")
    if re.fullmatch(r"\d{6,24}", slug):
        nav = f"https://www.facebook.com/profile.php?id={slug}"
        mbasic = f"https://mbasic.facebook.com/profile.php?id={slug}&v=timeline"
        post_base = f"https://www.facebook.com/{slug}"
        return nav, mbasic, post_base
    nav = f"https://www.facebook.com/{slug}"
    mbasic = f"https://mbasic.facebook.com/{slug}?v=timeline"
    post_base = f"https://www.facebook.com/{slug}"
    return nav, mbasic, post_base


def canonical_facebook_username_for_storage(raw: str) -> str:
    """
    Значение для поля ``Account.username`` (Facebook).

    - Числовой профиль (``profile.php?id=…`` или только цифры) → **только цифры** id.
    - Страница / vanity → **slug** из пути (один сегмент, без домена и query).

    Так проще уникальность ``(username, platform)`` и построение URL на клиенте.
    """
    nav, _, _ = normalize_facebook_profile_input(raw)
    p = urlparse(nav)
    path = (p.path or "/").rstrip("/") or "/"
    path_last = path.rsplit("/", 1)[-1].lower()
    if path_last == "profile.php":
        qs = parse_qs(p.query, keep_blank_values=True)
        ids = qs.get("id") or []
        pid = str(ids[0]).strip() if ids else ""
        if not re.fullmatch(r"\d{6,24}", pid):
            raise ValueError("Некорректный id профиля Facebook")
        return pid
    slug = path.strip("/").split("/")[0]
    if not slug or slug.lower() == "profile.php":
        raise ValueError("Не удалось извлечь идентификатор страницы Facebook")
    return unquote(slug)
