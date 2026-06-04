import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from platforms.tiktok import service as tiktok_service


def _ssr_html(*, video_count: int, item_count: int) -> str:
    items = [
        {
            "id": f"v{i}",
            "stats": {"playCount": 1},
            "author": {"uniqueId": "demo", "id": "1"},
        }
        for i in range(item_count)
    ]
    payload = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
                "userInfo": {
                    "user": {"uniqueId": "demo", "id": "1"},
                    "stats": {
                        "followerCount": 100,
                        "heartCount": 500,
                        "videoCount": video_count,
                    },
                }
            },
            "webapp.video-list": {"itemList": items},
        }
    }
    return (
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        f"{json.dumps(payload)}</script>"
    )


class TikTokForceWorkerTests(SimpleTestCase):
    def _fetch_with_mock_html(self, html: str):
        mock_response = MagicMock(status_code=200, text=html)
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(tiktok_service.httpx, "Client", return_value=mock_client):
            with patch.object(
                tiktok_service,
                "_run_worker",
                return_value=([], {"follower_text": "100"}),
            ) as run_worker:
                tiktok_service.fetch_tiktok_profile("demo")
        return run_worker

    @override_settings(TIKTOK_FORCE_WORKER=True)
    def test_force_worker_when_ssr_already_has_full_first_page(self):
        """40 постов в SSR и videoCount=40 — без force worker не нужен; с force — да."""
        run_worker = self._fetch_with_mock_html(_ssr_html(video_count=40, item_count=40))
        run_worker.assert_called()

    @override_settings(TIKTOK_FORCE_WORKER=False)
    def test_without_force_skips_worker_when_ssr_matches_video_count(self):
        run_worker = self._fetch_with_mock_html(_ssr_html(video_count=40, item_count=40))
        run_worker.assert_not_called()

    def test_tiktok_force_worker_helper_reads_settings(self):
        with override_settings(TIKTOK_FORCE_WORKER=True):
            self.assertTrue(tiktok_service._tiktok_force_worker())
        with override_settings(TIKTOK_FORCE_WORKER=False):
            self.assertFalse(tiktok_service._tiktok_force_worker())
