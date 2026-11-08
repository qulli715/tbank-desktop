# ui/update_check.py — проверка последнего релиза на GitHub.

from __future__ import annotations

import json
import urllib.error
import urllib.request

import config

API_URL = "https://api.github.com/repos/qulli715/tbank-desktop/releases/latest"
TIMEOUT_SECONDS = 8


def fetch_latest_release() -> dict | None:
    """Возвращает {"tag", "url"} последнего релиза или None при ошибке."""
    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": f"tbank-desktop/{config.APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return {"tag": str(data.get("tag_name") or ""), "url": str(data.get("html_url") or "")}


def normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("vV")


def is_newer(tag: str, version: str) -> bool:
    """Простое сравнение версий по числам (1.2.0 > 1.1.9)."""

    def parts(value: str) -> list[int]:
        result = []
        for chunk in normalize_tag(value).split("."):
            digits = "".join(ch for ch in chunk if ch.isdigit())
            result.append(int(digits) if digits else 0)
        return result

    current = parts(version)
    latest = parts(tag)
    length = max(len(current), len(latest))
    current += [0] * (length - len(current))
    latest += [0] * (length - len(latest))
    return latest > current
