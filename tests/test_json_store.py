import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.json_store import (
    load_json_object,
    update_json_object_atomic,
    write_json_object_atomic,
)


class JsonStoreTest(unittest.TestCase):
    def test_load_json_object_treats_missing_corrupted_and_non_object_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"

            self.assertEqual(load_json_object(path), {})

            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_json_object(path), {})

            path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(load_json_object(path), {})

    def test_update_json_object_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json_object_atomic(path, {"interval_minutes": 60})

            update_json_object_atomic(path, {"x": 100})

            self.assertEqual(load_json_object(path), {"interval_minutes": 60, "x": 100})

    def test_failed_atomic_replace_keeps_previous_file_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json_object_atomic(path, {"interval_minutes": 60})

            with patch("neurogate_usage_overlay.json_store.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    write_json_object_atomic(path, {"interval_minutes": 15})

            self.assertEqual(load_json_object(path), {"interval_minutes": 60})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
