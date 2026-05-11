"""Генерация CSV-отчёта по завершении автообновления (UTF-8 с BOM для Excel)."""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from django.utils import timezone


def _format_duration_human(seconds: int) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} ч. {m} м. {s} с."
    if m > 0:
        return f"{m} м. {s} с."
    return f"{s} с."


def _sum_post_after_column(rows: list[dict[str, Any]]) -> int:
    total = 0
    for r in rows:
        raw = r.get("post_after")
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        try:
            total += int(float(s))
        except Exception:
            continue
    return total


def build_auto_refresh_report_csv(
    *,
    rows: list[dict[str, Any]],
    started_at,
    finished_at,
    source: str,
    total_accounts: int,
    run_note: str,
    batch_post_total: int | None = None,
    dashboard_post_total: int | None = None,
    dashboard_account_count: int | None = None,
) -> str:
    """Возвращает текст CSV (без BOM — BOM добавляют при отдаче через HttpResponse)."""
    duration_sec = ""
    duration_human = ""
    if started_at and finished_at:
        duration_total = max(0, int((finished_at - started_at).total_seconds()))
        duration_sec = str(duration_total)
        duration_human = _format_duration_human(duration_total)

    def _fmt_dt(dt):
        if not dt:
            return ""
        return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S")

    status_counts = Counter(r.get("status", "") for r in rows)

    def _to_float(v: Any) -> float:
        try:
            return max(0.0, float(v))
        except Exception:
            return 0.0

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Параметр", "Значение"])
    w.writerow(["Начало (локальное время сервера)", _fmt_dt(started_at)])
    w.writerow(["Окончание", _fmt_dt(finished_at)])
    w.writerow(["Длительность", duration_human])
    w.writerow(["Длительность (сек)", duration_sec])
    w.writerow(["Источник", source or ""])
    w.writerow(["Всего аккаунтов в списке", str(total_accounts)])
    w.writerow(["Успешно (данные изменились)", str(status_counts.get("успешно", 0))])
    w.writerow(["Успешно (данные без изменений)", str(status_counts.get("успешно (данные без изменений)", 0))])
    w.writerow(["Ошибок", str(status_counts.get("ошибка", 0))])
    w.writerow(["Пропущено", str(status_counts.get("пропущен", 0))])
    w.writerow(["Не выполнено", str(status_counts.get("не выполнено", 0))])
    if run_note:
        w.writerow(["Примечание к прогону", run_note.replace("\n", " ").strip()[:2000]])

    by_platform: dict[str, dict[str, Any]] = {}
    by_profile: dict[str, dict[str, Any]] = {}
    for r in rows:
        plat = str(r.get("platform") or "").strip() or "unknown"
        prof = str(r.get("profile_name") or "").strip() or "Без профиля"
        elapsed = _to_float(r.get("elapsed_sec"))
        status = str(r.get("status") or "").strip().lower()

        p = by_platform.setdefault(plat, {"accounts": 0, "errors": 0, "elapsed": 0.0})
        p["accounts"] += 1
        p["elapsed"] += elapsed
        if "ошибка" in status:
            p["errors"] += 1

        g = by_profile.setdefault(prof, {"accounts": 0, "errors": 0, "elapsed": 0.0})
        g["accounts"] += 1
        g["elapsed"] += elapsed
        if "ошибка" in status:
            g["errors"] += 1

    w.writerow([])
    w.writerow(["Сводка по платформам", "", "", ""])
    w.writerow(["Платформа", "Аккаунтов", "Ошибок", "Суммарно"])
    for plat, agg in sorted(by_platform.items(), key=lambda kv: kv[1]["elapsed"], reverse=True):
        w.writerow([
            plat,
            agg["accounts"],
            agg["errors"],
            _format_duration_human(int(round(agg["elapsed"]))),
        ])

    w.writerow([])
    w.writerow(["Сводка по профилям", "", "", ""])
    w.writerow(["Профиль", "Аккаунтов", "Ошибок", "Суммарно"])
    for prof, agg in sorted(by_profile.items(), key=lambda kv: kv[1]["elapsed"], reverse=True):
        w.writerow([
            prof,
            agg["accounts"],
            agg["errors"],
            _format_duration_human(int(round(agg["elapsed"]))),
        ])

    w.writerow([])
    w.writerow([
        "Платформа",
        "Username",
        "Статус",
        "Подписчики (было)",
        "Подписчики (стало)",
        "Лайки (было)",
        "Лайки (стало)",
        "Просмотры (было)",
        "Просмотры (стало)",
        "Постов (было)",
        "Постов (стало)",
        "Пояснение",
    ])

    for r in rows:
        w.writerow([
            r.get("platform", ""),
            r.get("username", ""),
            r.get("status", ""),
            r.get("follower_before", ""),
            r.get("follower_after", ""),
            r.get("like_before", ""),
            r.get("like_after", ""),
            r.get("view_before", ""),
            r.get("view_after", ""),
            r.get("post_before", ""),
            r.get("post_after", ""),
            r.get("detail", ""),
        ])

    csv_posts_sum = _sum_post_after_column(rows)
    w.writerow([])
    w.writerow(["— Справка: суммы post_count (число публикаций на профиле по данным платформы) —"] + [""] * 11)
    line = [""] * 12
    line[0] = "Сумма колонки «Постов (стало)» по строкам этого файла"
    line[10] = str(csv_posts_sum)
    w.writerow(line)
    if batch_post_total is not None:
        line = [""] * 12
        line[0] = "Эталон: сумма post_count по аккаунтам очереди этого прогона (должна совпадать с суммой столбца, если все строки заполнены)"
        line[10] = str(int(batch_post_total))
        w.writerow(line)
    if dashboard_post_total is not None and dashboard_account_count is not None:
        line = [""] * 12
        line[0] = (
            "Эталон: сумма post_count по всем аккаунтам сводки дашборда "
            f"({int(dashboard_account_count)} акк., как GET /api/accounts/summary/ без скрытых платформ/профилей; "
            "включает недоступные, если они не скрыты — планировщик может их не обновлять)"
        )
        line[10] = str(int(dashboard_post_total))
        w.writerow(line)

    return buf.getvalue()
