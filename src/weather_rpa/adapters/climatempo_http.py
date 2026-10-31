"""Obtenção de HTML público, sem contornar bloqueios de acesso."""

import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ClimatempoError(RuntimeError):
    """Falha de acesso ou estrutura inesperada da fonte Climatempo."""


class ClimatempoHttpClient:
    """GET com timeout e tentativas limitadas; 403 é encerrado imediatamente."""

    def __init__(self, *, timeout=15.0, max_attempts=3, max_wait=60.0,
                 opener=urlopen, sleep=time.sleep, now=None):
        for name, value in (("timeout", timeout), ("max_wait", max_wait)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.timeout, self.max_attempts, self.max_wait = timeout, max_attempts, max_wait
        self._open, self._sleep = opener, sleep
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get(self, url: str) -> str:
        request = Request(url, headers={"Accept": "text/html", "User-Agent": "weather-rpa/0.1"})
        for attempt in range(self.max_attempts):
            delay = min(2 ** attempt, self.max_wait)
            try:
                with self._open(request, timeout=self.timeout) as response:
                    headers = getattr(response, "headers", None)
                    if headers is not None:
                        content_type = headers.get("Content-Type", "").split(";")[0].strip().lower()
                        if content_type and content_type not in ("text/html", "application/xhtml+xml"):
                            raise ClimatempoError("Expected an HTML response")
                    body = response.read()
            except HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                exc.close()
                if status not in (429, 500, 502, 503, 504) or attempt + 1 == self.max_attempts:
                    raise ClimatempoError(f"Climatempo HTTP {status}") from exc
                if retry_after:
                    delay = self._retry_delay(retry_after, delay)
            except (URLError, TimeoutError, ConnectionError, HTTPException) as exc:
                if attempt + 1 == self.max_attempts:
                    raise ClimatempoError("Climatempo request failed after bounded retries") from exc
            else:
                try:
                    return body.decode("utf-8")
                except UnicodeError as exc:
                    raise ClimatempoError("Climatempo returned invalid UTF-8") from exc
            self._sleep(delay)
        raise AssertionError("unreachable")

    def _retry_delay(self, raw: str, fallback: float) -> float:
        try:
            if raw.strip().isdigit():
                delay = int(raw.strip())
            else:
                deadline = parsedate_to_datetime(raw)
                if deadline.utcoffset() is None:
                    return fallback
                delay = max(0, (deadline - self._now()).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return fallback
        if delay > self.max_wait:
            raise ClimatempoError("Retry-After exceeds configured wait limit")
        return max(fallback, delay)
