from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from platforms.rumble import flaresolverr_client
from platforms.rumble.flaresolverr_client import (
    _FlareSolverrSession,
    _challenge_failure,
    _parse_fs_response,
    fetch_profile,
    release_shared_session,
)
from platforms.rumble.parse import feed_urls


class FlareSolverrClientTests(SimpleTestCase):
    def test_feed_urls_skip_bare_slug(self):
        urls = feed_urls("victor_lane19victor_lane19")
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("/user/" in u or "/c/" in u for u in urls))
        self.assertFalse(any(u.endswith("/victor_lane19victor_lane19") and "/user/" not in u and "/c/" not in u for u in urls))

    def test_parse_fs_response_error_json(self):
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {
            "status": "error",
            "message": "Error solving the challenge. Timeout after 60.0 seconds.",
        }
        with self.assertRaises(RuntimeError) as ctx:
            _parse_fs_response(resp)
        self.assertIn("Timeout", str(ctx.exception))

    def test_session_reuses_challenge_flag(self):
        sess = _FlareSolverrSession.__new__(_FlareSolverrSession)
        sess._client = MagicMock()
        sess._session_id = "test-session"
        sess._challenge_solved = False

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "status": "ok",
            "solution": {"response": "<html><title>ok</title></html>"},
        }
        sess._client.post.return_value = ok_resp

        html = sess.fetch_html("https://rumble.com/user/foo/about")
        self.assertIn("ok", html)
        self.assertTrue(sess._challenge_solved)

        call_payload = sess._client.post.call_args[1]["json"]
        self.assertEqual(call_payload["session"], "test-session")
        self.assertEqual(call_payload["maxTimeout"], 90_000)

        sess.fetch_html("https://rumble.com/user/foo")
        follow_payload = sess._client.post.call_args[1]["json"]
        self.assertEqual(follow_payload["maxTimeout"], 45_000)

    def test_challenge_failure_detector(self):
        self.assertTrue(_challenge_failure(RuntimeError("Timeout after 90.0 seconds")))
        self.assertFalse(_challenge_failure(ValueError("404 not found")))

    def test_fetch_profile_picks_feed_with_most_posts(self):
        release_shared_session()
        about_html = '<meta property="og:title" content="user">'
        feed_user = "<html>user feed no posts</html>"
        feed_c = (
            '<rum-video-thumbnail video-id="438302496" title="A" src="https://x/y.jpg"'
            ' url="https://rumble.com/shorts/abc123"></rum-video-thumbnail>'
        )
        sess = MagicMock()
        sess.fetch_html.side_effect = [
            feed_user,
            feed_c,
            about_html,
        ]
        with patch.object(flaresolverr_client, "_acquire_shared_session", return_value=sess):
            payload = fetch_profile("erick_spencer7")
        self.assertEqual(len(payload["_posts"]), 1)
        self.assertEqual(payload["_posts"][0]["external_id"], "438302496")

    def test_fetch_profile_non_authoritative_when_posts_missing(self):
        release_shared_session()
        about_html = (
            '<meta property="og:title" content="user">'
            "<p>2 videos</p>"
        )
        feed_html = "<html>no thumbnails</html>"
        sess = MagicMock()
        sess.fetch_html.side_effect = [feed_html, feed_html, about_html]
        with patch.object(flaresolverr_client, "_acquire_shared_session", return_value=sess):
            payload = fetch_profile("erick_spencer7")
        self.assertEqual(payload.get("_posts"), [])
        self.assertFalse(payload.get("_posts_authoritative", True))

    def test_fetch_profile_aborts_on_challenge_timeout(self):
        release_shared_session()
        sess = MagicMock()
        sess.fetch_html.side_effect = RuntimeError(
            "Error solving the challenge. Timeout after 90.0 seconds."
        )
        with patch.object(flaresolverr_client, "_acquire_shared_session", return_value=sess):
            with self.assertRaises(RuntimeError):
                fetch_profile("starrlanderboy")
        self.assertEqual(sess.fetch_html.call_count, 1)
