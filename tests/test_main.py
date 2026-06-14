import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.__main__ import _remove_pid_file, _write_pid_file


class MainPidFileTest(unittest.TestCase):
    def test_pid_file_is_removed_only_for_current_process(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "overlay.pid"
            with patch("neurogate_usage_overlay.__main__.os.getpid", return_value=1234):
                _write_pid_file(pid_file)
                self.assertEqual(pid_file.read_text(encoding="utf-8"), "1234")

            with patch("neurogate_usage_overlay.__main__.os.getpid", return_value=9999):
                _remove_pid_file(pid_file)
                self.assertTrue(pid_file.exists())

            with patch("neurogate_usage_overlay.__main__.os.getpid", return_value=1234):
                _remove_pid_file(pid_file)
                self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main()
