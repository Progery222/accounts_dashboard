"""Отправка отчёта автообновления в Telegram (Bot API)."""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from .auto_refresh_csv import extract_auto_refresh_status_counts

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_CANCEL_MARKERS = (
    "остановлено пользователем",
    "прервано перезапуском",
    "остановка до обработки",
)
_FILENAME_SAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


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


def resolve_telegram_bot_token() -> str:
    return (getattr(settings, "TELEGRAM_BOT_TOKEN", None) or "").strip()


def resolve_auto_refresh_chat_id(config) -> str:
    from_db = (getattr(config, "auto_refresh_telegram_chat_id", None) or "").strip()
    if from_db:
        return from_db
    return (getattr(settings, "TELEGRAM_AUTO_REFRESH_CHAT_ID", None) or "").strip()


def telegram_bot_configured() -> bool:
    return bool(resolve_telegram_bot_token())


def build_auto_refresh_telegram_text(
    *,
    rows: list[dict[str, Any]],
    started_at,
    finished_at,
    total_accounts: int,
) -> str:
    counts = extract_auto_refresh_status_counts(rows)
    lines = ["Автообновление завершено", ""]
    if total_accounts <= 0:
        lines.append("Нет аккаунтов для обновления (проверьте фильтры расписания).")
        lines.append("")
    lines.extend(
        [
            f"Успешно (данные изменились): {counts['ok_changed']}",
            f"Успешно (без изменений): {counts['ok_unchanged']}",
            f"Пропущено: {counts['skipped']}",
            f"Ошибки: {counts['error']}",
            f"Не выполнено: {counts['not_run']}",
            "",
        ]
    )
    duration_human = ""
    if started_at and finished_at:
        duration_human = _format_duration_human(
            int((finished_at - started_at).total_seconds()),
        )
    lines.extend(
        [
            f"Начало: {_fmt_dt(started_at)}",
            f"Окончание: {_fmt_dt(finished_at)}",
            f"Длительность: {duration_human or '—'}",
        ]
    )
    return "\n".join(lines)


def auto_refresh_report_filename(*, finished_at) -> str:
    if finished_at:
        stamp = timezone.localtime(finished_at).strftime("%Y-%m-%d_%H-%M")
    else:
        stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d_%H-%M")
    return f"auto_refresh_{stamp}.csv"


def should_send_auto_refresh_telegram(
    *,
    run_was_cancelled: bool,
    last_error: str,
) -> bool:
    if run_was_cancelled:
        return False
    err = (last_error or "").strip().lower()
    if err and any(m in err for m in _CANCEL_MARKERS):
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


def send_telegram_message(*, token: str, chat_id: str, text: str) -> None:
    _api_post(token, "sendMessage", chat_id=chat_id, text=text)


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
    chat_id = resolve_auto_refresh_chat_id(config)
    if not chat_id:
        raise RuntimeError("Chat ID не задан (настройки расписания или TELEGRAM_AUTO_REFRESH_CHAT_ID)")
    send_telegram_message(token=token, chat_id=chat_id, text=text)
    send_telegram_document(
        token=token,
        chat_id=chat_id,
        filename=filename,
        content=csv_body,
    )


def send_telegram_test_message(*, config, chat_id: str | None = None) -> None:
    token = resolve_telegram_bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в backend/.env")
    cid = (chat_id or "").strip() or resolve_auto_refresh_chat_id(config)
    if not cid:
        raise RuntimeError("Укажите Chat ID в настройках расписания")
    send_telegram_message(
        token=token,
        chat_id=cid,
        text="Проверка связи с ботом Accounts Stats. Автообновление: OK.",
    )
