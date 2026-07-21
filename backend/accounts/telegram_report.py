"""Отправка отчёта автообновления в Telegram (Bot API)."""

from __future__ import annotations

import io
import logging
import re
from collections import defaultdict
from datetime import timedelta
from typing import Any

import httpx
from django.conf import settings
from django.db.models import BigIntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .auto_refresh_csv import extract_auto_refresh_status_counts
from .telegram_chat_ids import normalize_telegram_chat_ids, telegram_chat_ids_from_config

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_CANCEL_MARKERS = (
    "остановлено пользователем",
    "прервано перезапуском",
    "остановка до обработки",
)
_FILENAME_SAFE = re.compile(r"[^\w.\-]+", re.UNICODE)
_NO_PROFILE = "Без профиля"
_NO_OWNER = "Без пользователя"
_METRIC_LABELS = (
    ("views", "👁", "Просмотры"),
    ("likes", "❤️", "Лайки"),
    ("followers", "👥", "Подписчики"),
    ("posts", "📝", "Публикации"),
)


def _format_duration_human(seconds: int) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} ч. {m} м. {s} с."
    if m > 0:
        return f"{m} м. {s} с."
    return f"{s} с."


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def _fmt_delta(n: int) -> str:
    value = int(n)
    if value > 0:
        return f"+{_fmt_int(value)}"
    return _fmt_int(value)


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def resolve_telegram_bot_token() -> str:
    return (getattr(settings, "TELEGRAM_BOT_TOKEN", None) or "").strip()


def resolve_auto_refresh_chat_ids(config) -> list[str]:
    ids = telegram_chat_ids_from_config(config)
    if ids:
        return ids
    env = (getattr(settings, "TELEGRAM_AUTO_REFRESH_CHAT_ID", None) or "").strip()
    return normalize_telegram_chat_ids(env)


def resolve_auto_refresh_chat_id(config) -> str:
    """Первый chat ID из списка (совместимость)."""
    ids = resolve_auto_refresh_chat_ids(config)
    return ids[0] if ids else ""


def telegram_bot_configured() -> bool:
    return bool(resolve_telegram_bot_token())


def _delta_period_days(config=None) -> int:
    if config is not None:
        raw = int(getattr(config, "account_delta_period_days", 1) or 1)
        return raw if raw in (1, 7, 30) else 1
    try:
        from .models import RefreshScheduleConfig

        raw = int(getattr(RefreshScheduleConfig.get(), "account_delta_period_days", 1) or 1)
        return raw if raw in (1, 7, 30) else 1
    except Exception:
        return 1


def _accounts_qs_for_telegram_stats(config=None):
    from .models import Account, AccountSnapshot
    from .views import _apply_visibility_filters

    qs = Account.objects.select_related("profile", "owner")
    include_archived = bool(getattr(config, "include_archived_accounts", False)) if config else False
    if not include_archived:
        qs = qs.filter(is_archived=False)
    qs = _apply_visibility_filters(
        qs,
        include_hidden_platforms=bool(
            getattr(config, "include_hidden_platform_accounts", False),
        ) if config else False,
        include_hidden_profiles=bool(
            getattr(config, "include_hidden_profile_accounts", False),
        ) if config else False,
    )
    period = _delta_period_days(config)
    cutoff = timezone.localdate() - timedelta(days=period)
    prev = AccountSnapshot.objects.filter(
        account=OuterRef("pk"),
        date__lte=cutoff,
    ).order_by("-date")
    return qs.annotate(
        _prev_view_count=Coalesce(
            Subquery(prev.values("view_count")[:1]),
            Value(0),
            output_field=BigIntegerField(),
        ),
        _prev_like_count=Coalesce(
            Subquery(prev.values("like_count")[:1]),
            Value(0),
            output_field=BigIntegerField(),
        ),
        _prev_follower_count=Coalesce(
            Subquery(prev.values("follower_count")[:1]),
            Value(0),
            output_field=BigIntegerField(),
        ),
        _prev_post_count=Coalesce(
            Subquery(prev.values("post_count")[:1]),
            Value(0),
            output_field=BigIntegerField(),
        ),
    )


def collect_profile_owner_stats(config=None) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """
    Агрегаты «всего / прирост» по профилям и владельцам.
    Прирост — как на дашборде (опорный снимок за account_delta_period_days).
    """
    empty = {"views": 0, "likes": 0, "followers": 0, "posts": 0,
             "views_d": 0, "likes_d": 0, "followers_d": 0, "posts_d": 0}
    by_profile: dict[str, dict] = defaultdict(lambda: dict(empty))
    by_owner: dict[str, dict] = defaultdict(lambda: dict(empty))

    for a in _accounts_qs_for_telegram_stats(config).iterator(chunk_size=500):
        pname = (a.profile.name if a.profile_id else _NO_PROFILE).strip() or _NO_PROFILE
        oname = (a.owner.name if a.owner_id else _NO_OWNER).strip() or _NO_OWNER
        cur = {
            "views": int(a.view_count or 0),
            "likes": int(a.like_count or 0),
            "followers": int(a.follower_count or 0),
            "posts": int(a.post_count or 0),
        }
        prev = {
            "views": int(getattr(a, "_prev_view_count", 0) or 0),
            "likes": int(getattr(a, "_prev_like_count", 0) or 0),
            "followers": int(getattr(a, "_prev_follower_count", 0) or 0),
            "posts": int(getattr(a, "_prev_post_count", 0) or 0),
        }
        for bucket_name, bucket in ((pname, by_profile), (oname, by_owner)):
            b = bucket[bucket_name]
            for k, v in cur.items():
                b[k] += v
                b[f"{k}_d"] += v - prev[k]

    profiles = sorted(by_profile.items(), key=lambda x: x[0].casefold())
    owners = sorted(by_owner.items(), key=lambda x: x[0].casefold())
    return profiles, owners


def _format_group_stats_block(title: str, emoji: str, groups: list[tuple[str, dict]]) -> list[str]:
    if not groups:
        return []
    lines = ["", f"{emoji} <b>{_html_escape(title)}</b>"]
    for name, st in groups:
        lines.append("")
        lines.append(f"• <b>{_html_escape(name)}</b>")
        for key, icon, label in _METRIC_LABELS:
            total = _fmt_int(st[key])
            delta = _fmt_delta(st[f"{key}_d"])
            lines.append(
                f"  {icon} {_html_escape(label)}: <b>{total}</b>  "
                f"<i>прирост {_html_escape(delta)}</i>",
            )
    return lines


def build_auto_refresh_telegram_text(
    *,
    rows: list[dict[str, Any]],
    started_at,
    finished_at,
    total_accounts: int,
    config=None,
    profile_stats: list[tuple[str, dict]] | None = None,
    owner_stats: list[tuple[str, dict]] | None = None,
) -> str:
    counts = extract_auto_refresh_status_counts(rows)
    lines = ["✅ <b>Автообновление завершено</b>", ""]
    if total_accounts <= 0:
        lines.append("⚠️ Нет аккаунтов для обновления (проверьте фильтры расписания).")
        lines.append("")
    lines.extend(
        [
            "📊 <b>Итоги прогона</b>",
            f"🟢 Успешно (данные изменились): <b>{counts['ok_changed']}</b>",
            f"⚪ Успешно (без изменений): <b>{counts['ok_unchanged']}</b>",
            f"⏭ Пропущено: <b>{counts['skipped']}</b>",
            f"🔴 Ошибки: <b>{counts['error']}</b>",
            f"⏸ Не выполнено: <b>{counts['not_run']}</b>",
            "",
            "🕐 <b>Время</b>",
        ]
    )
    duration_human = ""
    if started_at and finished_at:
        duration_human = _format_duration_human(
            int((finished_at - started_at).total_seconds()),
        )
    lines.extend(
        [
            f"Начало: <code>{_html_escape(_fmt_dt(started_at))}</code>",
            f"Окончание: <code>{_html_escape(_fmt_dt(finished_at))}</code>",
            f"Длительность: <b>{_html_escape(duration_human or '—')}</b>",
        ]
    )

    if profile_stats is None or owner_stats is None:
        try:
            collected_profiles, collected_owners = collect_profile_owner_stats(config)
            if profile_stats is None:
                profile_stats = collected_profiles
            if owner_stats is None:
                owner_stats = collected_owners
        except Exception:
            logger.exception("telegram_report.collect_profile_owner_stats_failed")
            profile_stats = profile_stats or []
            owner_stats = owner_stats or []

    lines.extend(_format_group_stats_block("Профили", "📁", profile_stats or []))
    lines.extend(_format_group_stats_block("Пользователи", "👤", owner_stats or []))
    return "\n".join(lines)


def auto_refresh_report_filename(*, finished_at) -> str:
    if finished_at:
        stamp = timezone.localtime(finished_at).strftime("%Y-%m-%d_%H-%M")
    else:
        stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d_%H-%M")
    return f"auto_refresh_{stamp}.csv"


def _run_detail_unstarted(run_detail: dict[str, Any] | None) -> bool:
    items = list((run_detail or {}).get("items") or [])
    if not items:
        return True
    pending = {"queued", "running", ""}
    return all(str(it.get("status") or "").strip().lower() in pending for it in items)


def should_send_auto_refresh_telegram(
    *,
    run_was_cancelled: bool,
    last_error: str,
    report_rows: list[dict[str, Any]] | None = None,
    started_at=None,
    finished_at=None,
    run_detail: dict[str, Any] | None = None,
    min_duration_sec: float = 30.0,
) -> bool:
    if run_was_cancelled:
        return False
    err = (last_error or "").strip().lower()
    if err and any(m in err for m in _CANCEL_MARKERS):
        return False
    rows = report_rows or []
    counts = extract_auto_refresh_status_counts(rows)
    any_work = any(int(counts.get(k) or 0) > 0 for k in counts)
    elapsed = 0.0
    if started_at and finished_at:
        elapsed = max(0.0, (finished_at - started_at).total_seconds())
    if not any_work and _run_detail_unstarted(run_detail) and elapsed < max(
        5.0,
        float(min_duration_sec),
    ):
        return False
    if not any_work and started_at and finished_at and elapsed < max(5.0, float(min_duration_sec)):
        return False
    return True


def _api_post(token: str, method: str, **payload) -> dict:
    url = f"{_TELEGRAM_API}/bot{token}/{method}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        data = resp.json()
    if not data.get("ok"):
        desc = data.get("description") or resp.text or f"HTTP {resp.status_code}"
        raise RuntimeError(str(desc))
    return data


def send_telegram_message(*, token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    _api_post(token, "sendMessage", **payload)


def send_telegram_document(
    *,
    token: str,
    chat_id: str,
    filename: str,
    content: str,
) -> None:
    safe_name = _FILENAME_SAFE.sub("_", filename) or "auto_refresh.csv"
    body = (content or "").encode("utf-8-sig")
    url = f"{_TELEGRAM_API}/bot{token}/sendDocument"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            data={"chat_id": chat_id},
            files={"document": (safe_name, io.BytesIO(body), "text/csv")},
        )
        data = resp.json()
    if not data.get("ok"):
        desc = data.get("description") or resp.text or f"HTTP {resp.status_code}"
        raise RuntimeError(str(desc))


def send_auto_refresh_telegram_report(
    *,
    config,
    text: str,
    csv_body: str,
    filename: str,
) -> None:
    token = resolve_telegram_bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в окружении")
    chat_ids = resolve_auto_refresh_chat_ids(config)
    if not chat_ids:
        raise RuntimeError(
            "Chat ID не задан (добавьте получателей в настройках расписания "
            "или TELEGRAM_AUTO_REFRESH_CHAT_ID в .env)",
        )
    errors: list[str] = []
    for chat_id in chat_ids:
        try:
            send_telegram_message(token=token, chat_id=chat_id, text=text)
            send_telegram_document(
                token=token,
                chat_id=chat_id,
                filename=filename,
                content=csv_body,
            )
        except Exception as exc:
            errors.append(f"{chat_id}: {exc}")
    if errors:
        if len(errors) == len(chat_ids):
            raise RuntimeError(errors[0])
        raise RuntimeError(
            f"Не удалось отправить всем получателям ({len(errors)} из {len(chat_ids)}): "
            + "; ".join(errors[:3]),
        )


def send_telegram_test_message(
    *,
    config,
    chat_id: str | None = None,
    chat_ids: list[str] | None = None,
) -> None:
    token = resolve_telegram_bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в backend/.env")
    targets = normalize_telegram_chat_ids(chat_ids) if chat_ids is not None else []
    if not targets:
        single = (chat_id or "").strip()
        if single:
            targets = normalize_telegram_chat_ids(single)
        else:
            targets = resolve_auto_refresh_chat_ids(config)
    if not targets:
        raise RuntimeError("Укажите хотя бы один Chat ID в настройках расписания")
    text = "Проверка связи с ботом Accounts Stats. Автообновление: OK."
    errors: list[str] = []
    for cid in targets:
        try:
            send_telegram_message(token=token, chat_id=cid, text=text)
        except Exception as exc:
            errors.append(f"{cid}: {exc}")
    if errors:
        if len(errors) == len(targets):
            raise RuntimeError(errors[0])
        raise RuntimeError(
            f"Ошибка для {len(errors)} из {len(targets)} chat ID: " + "; ".join(errors[:3]),
        )
