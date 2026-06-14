from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpSettings:
    timeout_seconds: float = 30.0
    request_delay_seconds: float = 1.0
    jitter_seconds: float = 0.25
    retry_total: int = 5
    backoff_factor: float = 1.0
    user_agent: str = (
        "vietlott-history-collector/0.1 (scientific data collection; contact: configure-your-email)"
    )


class RateLimiter:
    def __init__(self, delay_seconds: float, jitter_seconds: float) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self.jitter_seconds = max(0.0, jitter_seconds)
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            target_delay = self.delay_seconds + random.uniform(0.0, self.jitter_seconds)
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < target_delay:
                time.sleep(target_delay - elapsed)
            self._last_request_at = time.monotonic()


class HttpClient:
    def __init__(
        self,
        settings: HttpSettings,
        *,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.rate_limiter = rate_limiter or RateLimiter(
            settings.request_delay_seconds,
            settings.jitter_seconds,
        )
        self.session = requests.Session()
        retry = Retry(
            total=settings.retry_total,
            connect=settings.retry_total,
            read=settings.retry_total,
            status=settings.retry_total,
            allowed_methods=frozenset({"GET", "POST"}),
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            backoff_factor=settings.backoff_factor,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.6",
            }
        )

    def get_text(self, url: str, **kwargs: Any) -> str:
        response = self._request("GET", url, **kwargs)
        return response.text

    def post_json(self, url: str, *, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        response = self._request(
            "POST",
            url,
            data=json.dumps(body, ensure_ascii=False),
            headers=headers,
        )
        try:
            value = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Vietlott returned non-JSON content for {url}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Unexpected JSON response type for {url}: {type(value).__name__}")
        return value

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.rate_limiter.wait()
        LOGGER.debug("%s %s", method, url)
        response = self.session.request(
            method,
            url,
            timeout=self.settings.timeout_seconds,
            **kwargs,
        )
        if response.status_code >= 400:
            excerpt = response.text[:300].replace("\n", " ")
            raise requests.HTTPError(
                f"{method} {url} failed with HTTP {response.status_code}: {excerpt}",
                response=response,
            )
        response.encoding = response.apparent_encoding or response.encoding
        return response

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
