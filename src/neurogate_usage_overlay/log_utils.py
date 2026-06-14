from __future__ import annotations

from pathlib import Path


DEFAULT_MAX_LOG_BYTES = 256 * 1024
DEFAULT_TRIM_TO_BYTES = 128 * 1024


def append_bounded_log(
    path: Path,
    line: str,
    *,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    trim_to_bytes: int = DEFAULT_TRIM_TO_BYTES,
) -> None:
    """Append one log line and keep the file bounded.

    The overlay logs operational state from a private account page. Keeping only
    a small recent tail reduces both disk growth and unnecessary local exposure.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_bytes:
        tail = path.read_bytes()[-trim_to_bytes:]
        path.write_bytes(tail)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
