import unittest
from pathlib import Path

from platforms.worker_utils import chrome_cmdline_matches_user_data_dir


class ChromeProfileKillMatchTests(unittest.TestCase):
    def test_exact_base_dir_not_subdir(self):
        base = r"C:\Users\Me\AppData\Local\TikStatsChromeProfile"
        tiktok = base + r"\tiktok_chrome_authorized"
        cmd_base = f'chrome.exe --user-data-dir="{base}" --no-first-run'
        cmd_tt = f'chrome.exe --user-data-dir="{tiktok}" --no-first-run'
        assert chrome_cmdline_matches_user_data_dir(cmd_base, base)
        assert not chrome_cmdline_matches_user_data_dir(cmd_tt, base)
        assert chrome_cmdline_matches_user_data_dir(cmd_tt, tiktok)

    def test_unquoted_flag(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            prof = str(Path(tmp).resolve())
            cmd = f"/usr/bin/chromium --user-data-dir={prof} --disable-gpu"
            assert chrome_cmdline_matches_user_data_dir(cmd, prof)
            if os.name == "nt":
                cmd_win = f'chrome.exe --user-data-dir="{prof}"'
                assert chrome_cmdline_matches_user_data_dir(cmd_win, prof)
