#!/usr/bin/env python3
"""One-shot: schedule + auto-refresh state (server diagnostic)."""
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["RUN_SCHEDULER"] = "false"

import django

django.setup()

from accounts.models import AutoRefreshState, RefreshAllState, RefreshScheduleConfig
from accounts.auto_refresh_progress import progress_from_run_detail, refresh_run_in_progress

cfg = RefreshScheduleConfig.get()
auto = AutoRefreshState.get()
rr = RefreshAllState.get()

auto_src = (auto.source or "").strip()
auto_active = refresh_run_in_progress(auto, source=auto_src)
rr_active = refresh_run_in_progress(rr, source="refresh_all")

rd = auto.run_detail if isinstance(auto.run_detail, dict) else {}
done, total, progress = progress_from_run_detail(
    rd,
    db_total=int(auto.total_accounts or 0),
    db_done=int(auto.processed_accounts or 0),
)

out = {
    "schedule": {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "interval_hours": cfg.interval_hours,
        "times": cfg.times,
        "skip_recent_hours": cfg.skip_recent_hours,
        "platforms_filter": cfg.auto_refresh_platforms or "all",
        "profile_ids_filter": cfg.auto_refresh_profile_ids or "all",
        "owner_ids_filter": cfg.auto_refresh_owner_ids or "all",
        "include_hidden_platforms": cfg.include_hidden_platform_accounts,
        "include_hidden_profiles": cfg.include_hidden_profile_accounts,
        "include_unavailable": cfg.include_unavailable_accounts,
        "delta_period_days": cfg.account_delta_period_days,
    },
    "auto_refresh": {
        "is_running": bool(auto_active or rr_active),
        "auto_active": auto_active,
        "refresh_all_active": rr_active,
        "source": auto_src or None,
        "cancel_requested": bool(auto.cancel_requested or rr.cancel_requested),
        "processed": done,
        "total": total,
        "progress_percent": progress,
        "success": int(auto.success_accounts or 0),
        "failed": int(auto.failed_accounts or 0),
        "current_account": auto.current_account or rr.current_account,
        "started_at": str(auto.started_at or rr.started_at or ""),
        "finished_at": str(auto.finished_at or rr.finished_at or ""),
        "last_error": (auto.last_error or rr.last_error or "")[:500] or None,
    },
    "refresh_all": {
        "is_running": bool(rr.is_running),
        "processed": int(rr.processed_accounts or 0),
        "total": int(rr.total_accounts or 0),
        "started_at": str(rr.started_at or ""),
        "finished_at": str(rr.finished_at or ""),
    },
}

print(json.dumps(out, ensure_ascii=False, indent=2))
