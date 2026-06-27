from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any


API_BASE_URL = "https://api.vibemod.pro"
ENDPOINTS = (
    "/client/me",
    "/client/usage/limits",
    "/client/api-keys/summary",
    "/client/usage-records",
)
SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "key",
    "email",
    "phone",
    "name",
    "login",
)


def _read_api_key() -> str:
    value = os.environ.get("VIBEMODE_API_KEY", "").strip()
    if value:
        return value
    return getpass.getpass("Vibemode API key (hidden): ").strip()


def _request_json(path: str, api_key: str, timeout: float) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "vibemode-contract-check/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body[:200]
        return exc.code, payload


def _safe_shape(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(str(item) for item in value.keys()):
            lowered = key.lower()
            if any(word in lowered for word in SENSITIVE_KEYWORDS):
                result[key] = "<redacted>"
                continue
            item = value.get(key)
            if isinstance(item, (dict, list)):
                result[key] = _safe_shape(item, depth + 1)
            else:
                result[key] = type(item).__name__
        return result
    if isinstance(value, list):
        if not value:
            return []
        return [_safe_shape(value[0], depth + 1), f"... {len(value)} item(s) total"]
    return type(value).__name__


def _interesting_fields(payload: Any) -> list[str]:
    found: list[str] = []
    wanted = (
        "currentPlanName",
        "currentPlanEndsAt",
        "credits_used_5h",
        "credits_limit_5h",
        "credits_used_7d",
        "credits_limit_7d",
        "rows",
    )

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key) in wanted:
                    found.append(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value[:3]:
                walk(item)

    walk(payload)
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check which Vibemode API contract fields are available for an API key."
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    api_key = _read_api_key()
    if not api_key:
        print("No API key provided.")
        return 2

    print("Checking Vibemode API contract. The API key will not be printed.")
    print(f"Base URL: {API_BASE_URL}")
    overall_ok = True

    for path in ENDPOINTS:
        try:
            status, payload = _request_json(path, api_key, args.timeout)
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic script.
            overall_ok = False
            print(f"\n{path}: request failed: {type(exc).__name__}: {exc}")
            continue

        ok = 200 <= status < 300
        overall_ok = overall_ok and ok
        print(f"\n{path}: HTTP {status}")
        print("shape:")
        print(json.dumps(_safe_shape(payload), ensure_ascii=False, indent=2))
        fields = _interesting_fields(payload)
        if fields:
            print("interesting fields:", ", ".join(fields))

    if overall_ok:
        print("\nResult: all checked endpoints are available.")
        return 0
    print("\nResult: at least one endpoint is unavailable for this key.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
