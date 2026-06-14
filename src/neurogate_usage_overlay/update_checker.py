from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


DEFAULT_RELEASE_API_URL = "https://api.github.com/repos/RyandavisProject/neurogate-overlay/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    release_zip_url: str | None = None
    release_sha256: str | None = None

    @property
    def latest_label(self) -> str:
        return f"v{self.latest_version}"


def latest_release_api_url() -> str:
    return os.environ.get("NEUROGATE_UPDATE_API_URL", DEFAULT_RELEASE_API_URL)


def normalize_version(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    return cleaned


def version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in normalize_version(value).split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits or "0"))
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    left = version_key(candidate)
    right = version_key(current)
    length = max(len(left), len(right))
    return left + (0,) * (length - len(left)) > right + (0,) * (length - len(right))


def _release_asset_info(payload: dict[str, object]) -> tuple[str | None, str | None]:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None, None

    zip_asset: dict[str, object] | None = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        url = str(item.get("browser_download_url") or "")
        if not url or not name.endswith(".zip"):
            continue
        if zip_asset is None or "neurogate-overlay" in name:
            zip_asset = item
        if "neurogate-overlay" in name:
            break

    if not zip_asset:
        return None, None

    digest = str(zip_asset.get("digest") or "")
    sha256 = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else None
    return str(zip_asset.get("browser_download_url") or "") or None, sha256


def check_for_update(
    current_version: str = __version__,
    api_url: str | None = None,
    timeout_seconds: float = 3.0,
) -> UpdateInfo | None:
    request = Request(
        api_url or latest_release_api_url(),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"neurogate-overlay/{current_version}",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    tag_name = str(payload.get("tag_name") or "")
    latest_version = normalize_version(tag_name)
    release_url = str(payload.get("html_url") or "")
    if not latest_version or not release_url:
        return None
    if not is_newer_version(latest_version, current_version):
        return None
    release_zip_url, release_sha256 = _release_asset_info(payload)
    return UpdateInfo(
        current_version=normalize_version(current_version),
        latest_version=latest_version,
        release_url=release_url,
        release_zip_url=release_zip_url,
        release_sha256=release_sha256,
    )
