"""Small cached HTTP client used by the public-data adapters."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


class HttpClient:
    def __init__(self, cache_dir: str | Path | None = None, timeout: int = 60):
        configured = cache_dir or os.environ.get("WEATHER_CACHE_DIR")
        self.cache_dir = Path(configured or "var/weather-cache")
        self.timeout = timeout

    def get_bytes(self, url: str, ttl_seconds: int | None = None) -> bytes:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self.cache_dir / key
        if path.exists() and (
            ttl_seconds is None
            or time.time() - path.stat().st_mtime <= ttl_seconds
        ):
            return path.read_bytes()

        request = Request(
            url,
            headers={"User-Agent": "DisasterData-Weather/0.1 (public-data client)"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = response.read()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return payload

    def get_text(self, url: str, ttl_seconds: int | None = None) -> str:
        return self.get_bytes(url, ttl_seconds).decode("utf-8")

    def get_json(self, url: str, ttl_seconds: int | None = None) -> Any:
        return json.loads(self.get_text(url, ttl_seconds))

