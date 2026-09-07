from django.test import SimpleTestCase
from unittest.mock import patch

from platforms.challenge_solver import challenge_solver_urls


class ChallengeSolverUrlsTests(SimpleTestCase):
    def test_explicit_list(self):
        with patch.dict(
            "os.environ",
            {
                "CHALLENGE_SOLVER_URLS": "http://a/v1, http://b/v1",
                "BYPARR_URL": "http://ignored/v1",
            },
            clear=False,
        ):
            self.assertEqual(
                challenge_solver_urls(),
                ["http://a/v1", "http://b/v1"],
            )

    def test_named_order_byparr_solverr_flare(self):
        env = {
            "CHALLENGE_SOLVER_URLS": "",
            "BYPARR_URL": "http://byparr/v1",
            "SOLVERR_URL": "http://solverr/v1",
            "FLARESOLVERR_URL": "http://flare/v1",
        }
        with patch.dict("os.environ", env, clear=False):
            self.assertEqual(
                challenge_solver_urls(),
                ["http://byparr/v1", "http://solverr/v1", "http://flare/v1"],
            )
