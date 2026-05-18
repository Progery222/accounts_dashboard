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
        "ID аккаунта",
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
            r.get("account_id", ""),
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
    w.writerow(["— Справка: суммы post_count (число публикаций на профиле по данным платформы) —"] + [""] * 12)
    line = [""] * 13
    line[0] = "Сумма колонки «Постов (стало)» по строкам этого файла"
    line[11] = str(csv_posts_sum)
    w.writerow(line)
    if batch_post_total is not None:
        line = [""] * 13
        line[0] = "Эталон: сумма post_count по аккаунтам очереди этого прогона (должна совпадать с суммой столбца, если все строки заполнены)"
        line[11] = str(int(batch_post_total))
        w.writerow(line)
    if dashboard_post_total is not None and dashboard_account_count is not None:
        line = [""] * 13
        line[0] = (
            "Эталон: сумма post_count по всем аккаунтам сводки дашборда "
            f"({int(dashboard_account_count)} акк., как GET /api/accounts/summary/ без скрытых платформ/профилей; "
            "включает недоступные, если они не скрыты — планировщик может их не обновлять)"
        )
        line[11] = str(int(dashboard_post_total))
        w.writerow(line)

    return buf.getvalue()


def collect_auto_refresh_report_rows(
    report_by_index: list[dict | None],
    accounts: list,
    *,
    not_done_detail: str = "остановка до обработки этого аккаунта",
) -> list[dict]:
    """Собирает строки отчёта: обработанные + «не выполнено» для оставшихся в очереди."""
    rows: list[dict] = []
    n = min(len(report_by_index), len(accounts))
    for i in range(n):
        row = report_by_index[i]
        if row is not None:
            rows.append(row)
            continue
        acc = accounts[i]
        try:
            acc.refresh_from_db()
        except Exception:
            pass
        fb = int(getattr(acc, "follower_count", 0) or 0)
        lb = int(getattr(acc, "like_count", 0) or 0)
        vb = int(getattr(acc, "view_count", 0) or 0)
        pb = int(getattr(acc, "post_count", 0) or 0)
        prof = "Без профиля"
        if getattr(acc, "profile_id", None) and getattr(acc, "profile", None):
            prof = acc.profile.name or "Без профиля"
        rows.append(
            {
                "account_id": acc.id,
                "platform": acc.platform,
                "username": acc.username,
                "profile_name": prof,
                "status": "не выполнено",
                "follower_before": fb,
                "follower_after": fb,
                "like_before": lb,
                "like_after": lb,
                "view_before": vb,
                "view_after": vb,
                "post_before": pb,
                "post_after": pb,
                "elapsed_sec": "",
                "detail": not_done_detail,
            },
        )
    return rows


def extract_error_account_ids_from_saved_auto_refresh_csv(csv_text: str) -> list[int]:
    """
    Из текста CSV, сохранённого в AutoRefreshState.last_report_csv (тот же, что отдаёт
    GET /api/accounts/auto-refresh-report/), извлекает id аккаунтов со статусом «ошибка».

    Поддерживается формат с колонкой «ID аккаунта» и старый (только платформа/username)
    — для него выполняется поиск Account по (platform, username).
    """
    if not (csv_text or "").strip():
        return []

    text = csv_text.lstrip("\ufeff").strip("\r\n")
    buf = io.StringIO(text)
    reader = csv.reader(buf, delimiter=";")
    rows: list[list[str]] = []
    for row in reader:
        rows.append([str(c or "").strip() for c in row])

    header_idx = -1
    mode: str | None = None
    for i, row in enumerate(rows):
        if not row:
            continue
        if row[0] == "ID аккаунта" and len(row) >= 4:
            header_idx = i
            mode = "id_column"
            break
        if row[0] == "Платформа" and len(row) >= 3 and row[2] == "Статус":
            header_idx = i
            mode = "legacy"
            break

    if header_idx < 0 or not mode:
        return []

    def _is_footer_start(cell: str) -> bool:
        if not cell:
            return False
        c = cell.strip()
        if c.startswith("—") or c.startswith("Сумма") or c.startswith("Эталон"):
            return True
        if c.startswith("-"):
            return True
        return False

    ids: list[int] = []

    if mode == "id_column":
        for row in rows[header_idx + 1 :]:
            if not row or not any(cell for cell in row):
                continue
            if _is_footer_start(row[0]):
                break
            if len(row) < 4:
                continue
            if "ошибка" not in row[3].lower():
                continue
            if not row[0]:
                continue
            try:
                ids.append(int(row[0]))
            except ValueError:
                continue
        return sorted(set(ids))

    from accounts.models import Account

    for row in rows[header_idx + 1 :]:
        if not row or not any(cell for cell in row):
            continue
        if _is_footer_start(row[0]):
            break
        if len(row) < 3:
            continue
        if "ошибка" not in row[2].lower():
            continue
        plat = (row[0] or "").strip().lower()
        user = (row[1] or "").strip().lstrip("@").lower()
        if not plat or not user:
            continue
        pk = (
            Account.objects.filter(platform=plat, username__iexact=user)
            .values_list("pk", flat=True)
            .first()
        )
        if pk is not None:
            ids.append(int(pk))

    return sorted(set(ids))
