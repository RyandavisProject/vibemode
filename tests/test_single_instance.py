import tempfile
import unittest
from pathlib import Path

from neurogate_usage_overlay.single_instance import SingleInstanceLock


class SingleInstanceLockTest(unittest.TestCase):
    def test_second_lock_is_rejected_until_first_is_released(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "overlay.lock"
            first = SingleInstanceLock(lock_path)
            second = SingleInstanceLock(lock_path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())

            first.release()

            self.assertTrue(second.acquire())
            second.release()

    def test_existing_non_empty_lock_file_still_rejects_second_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "overlay.lock"
            lock_path.write_text("previous run", encoding="utf-8")
            first = SingleInstanceLock(lock_path)
            second = SingleInstanceLock(lock_path)

            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.release()

    def test_context_manager_raises_when_lock_is_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "overlay.lock"
            first = SingleInstanceLock(lock_path)
            self.assertTrue(first.acquire())
            try:
                with self.assertRaises(RuntimeError):
                    with SingleInstanceLock(lock_path):
                        pass
            finally:
                first.release()
