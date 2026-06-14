import tempfile
import unittest
from pathlib import Path

from neurogate_usage_overlay.log_utils import append_bounded_log


class LogUtilsTest(unittest.TestCase):
    def test_append_bounded_log_trims_old_content(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "overlay.log"
            log_path.write_text("A" * 100, encoding="utf-8")

            append_bounded_log(log_path, "fresh\n", max_bytes=50, trim_to_bytes=10)

            content = log_path.read_text(encoding="utf-8")
            self.assertLessEqual(len(content), 16)
            self.assertTrue(content.endswith("fresh\n"))


if __name__ == "__main__":
    unittest.main()
