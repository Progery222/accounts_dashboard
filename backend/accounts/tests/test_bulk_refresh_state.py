"""Состояние bulk refresh: стартовый сброс и активный прогон."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from accounts.auto_refresh_progress import refresh_run_in_progress
from accounts.models import Platform
from accounts.refresh_state import should_clear_stale_refresh_on_startup
from accounts.views import _parallel_refresh_worker_count


class BulkRefreshStateTests(SimpleTestCase):
    def test_should_not_clear_on_script_startup(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RUN_MAIN", None)
            with patch("accounts.refresh_state.sys.argv", ["scripts/foo.py"]):
                self.assertFalse(should_clear_stale_refresh_on_startup())

    def test_should_clear_on_runserver_child(self):
        with patch.dict(os.environ, {"RUN_MAIN": "true"}, clear=False):
            with patch("accounts.refresh_state.sys.argv", ["manage.py", "runserver"]):
                self.assertTrue(should_clear_stale_refresh_on_startup())

    def test_refresh_run_in_progress_from_run_detail(self):
        class Stub:
            is_running = False
            finished_at = None
            source = "bulk_refresh"
            started_at = object()
            run_detail = {
                "items": [
                    {"status": "done"},
                    {"status": "running"},
                ],
            }

        self.assertTrue(refresh_run_in_progress(Stub(), source="bulk_refresh"))

    def test_refresh_run_finished(self):
        class Stub:
            is_running = False
            finished_at = object()
            source = "bulk_refresh"
            run_detail = {"items": [{"status": "queued"}]}

        self.assertFalse(refresh_run_in_progress(Stub(), source="bulk_refresh"))

    def test_parallel_workers_at_least_platform_count(self):
        accounts = [
            MagicMock(platform=Platform.FACEBOOK),
            MagicMock(platform=Platform.TIKTOK),
            MagicMock(platform=Platform.INSTAGRAM),
            MagicMock(platform=Platform.THREADS),
            MagicMock(platform=Platform.YOUTUBE),
            MagicMock(platform=Platform.X),
        ]
        with patch.dict(os.environ, {"AUTO_REFRESH_WORKERS": "1"}, clear=False):
            n = _parallel_refresh_worker_count(accounts)
        self.assertGreaterEqual(n, 6)

    def test_parallel_workers_capped_for_single_platform(self):
        accounts = [MagicMock(platform=Platform.TIKTOK) for _ in range(5)]
        with patch.dict(os.environ, {"AUTO_REFRESH_WORKERS": "8"}, clear=False):
            n = _parallel_refresh_worker_count(accounts)
        self.assertEqual(n, 1)
