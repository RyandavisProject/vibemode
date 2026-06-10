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
    return UpdateInfo(
        current_version=normalize_version(current_version),
        latest_version=latest_version,
        release_url=release_url,
    )
