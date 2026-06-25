import json
import unittest
from unittest.mock import patch

from neurogate_usage_overlay.update_checker import (
    check_for_update,
    is_newer_version,
    latest_release_api_url,
    normalize_version,
    _release_asset_info,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class UpdateCheckerTest(unittest.TestCase):
    def test_normalize_version_strips_v_prefix(self):
        self.assertEqual(normalize_version("v1.5.0"), "1.5.0")

    def test_latest_release_api_url_uses_vibemod_repo(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                latest_release_api_url(),
                "https://api.github.com/repos/RyandavisProject/vibemod/releases/latest",
            )

    def test_is_newer_version_compares_semver_parts(self):
        self.assertTrue(is_newer_version("v1.5.1", "1.5.0"))
        self.assertTrue(is_newer_version("v1.6.0", "1.5.9"))
        self.assertFalse(is_newer_version("v1.5.0", "1.5.0"))
        self.assertFalse(is_newer_version("v1.4.9", "1.5.0"))

    def test_check_for_update_returns_latest_release(self):
        payload = {
            "tag_name": "v1.5.1",
            "html_url": "https://github.com/RyandavisProject/neurogate-overlay/releases/tag/v1.5.1",
        }
        with patch("neurogate_usage_overlay.update_checker.urlopen", return_value=FakeResponse(payload)):
            info = check_for_update(current_version="1.5.0", api_url="https://example.test/latest")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.latest_label, "v1.5.1")
        self.assertEqual(info.current_version, "1.5.0")

    def test_check_for_update_prefers_release_zip_asset(self):
        payload = {
            "tag_name": "v1.7.0",
            "html_url": "https://github.com/RyandavisProject/neurogate-overlay/releases/tag/v1.7.0",
            "assets": [
                {
                    "name": "notes.txt",
                    "browser_download_url": "https://example.test/notes.txt",
                },
                {
                    "name": "neurogate-overlay-v1.7.0.zip",
                    "browser_download_url": "https://example.test/neurogate-overlay-v1.7.0.zip",
                    "digest": "sha256:" + "a" * 64,
                },
            ],
        }
        with patch("neurogate_usage_overlay.update_checker.urlopen", return_value=FakeResponse(payload)):
            info = check_for_update(current_version="1.6.0", api_url="https://example.test/latest")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.release_zip_url, "https://example.test/neurogate-overlay-v1.7.0.zip")
        self.assertEqual(info.release_sha256, "a" * 64)

    def test_release_asset_info_ignores_source_archives_without_assets(self):
        self.assertEqual(_release_asset_info({"zipball_url": "https://example.test/source.zip"}), (None, None))

    def test_check_for_update_ignores_current_release(self):
        payload = {
            "tag_name": "v1.5.0",
            "html_url": "https://github.com/RyandavisProject/neurogate-overlay/releases/tag/v1.5.0",
        }
        with patch("neurogate_usage_overlay.update_checker.urlopen", return_value=FakeResponse(payload)):
            self.assertIsNone(check_for_update(current_version="1.5.0", api_url="https://example.test/latest"))

    def test_check_for_update_returns_none_on_network_error(self):
        with patch("neurogate_usage_overlay.update_checker.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(check_for_update(current_version="1.5.0", api_url="https://example.test/latest"))


if __name__ == "__main__":
    unittest.main()
