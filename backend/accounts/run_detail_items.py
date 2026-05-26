"""Поля run_detail.items для модалки «Подробнее» (очередь автообновления / refresh_all)."""
from __future__ import annotations

from django.utils import timezone

# В UI показываем время попадания в эти списки.
_STATUS_AT_ON = frozenset({"done", "skipped", "error"})


def merge_run_detail_item(existing: dict, patch: dict) -> dict:
    """Слить patch в item; при переходе в done/skipped/error — ISO-время в status_at."""
    merged = {**existing, **patch}
    if "status" not in patch:
        return merged
    new_status = str(patch.get("status") or "").strip().lower()
    old_status = str(existing.get("status") or "").strip().lower()
    if new_status in _STATUS_AT_ON and new_status != old_status:
        merged["status_at"] = timezone.now().isoformat()
    return merged
