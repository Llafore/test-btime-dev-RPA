"""Transporte JSON com timeout e retentativas limitadas para Open-Meteo."""

import json
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OpenMeteoError(RuntimeError):
    """Falha de transporte ou de contrato da fonte Open-Meteo."""


class OpenMeteoHttpClient:
    """Retenta GET em falhas transitórias; não retenta erro de dados ou HTTP 4xx.

    Retry-After superior ao limite de espera encerra a operação, sem tentar antes
    do prazo indicado. Opener, espera e relógio podem ser substituídos nos testes.
    """

    def __init__(self, *, timeout=15.0, max_attempts=3, max_wait=60.0,
                 opener=urlopen, sleep=time.sleep, now=None):
        for name, value in (("timeout", timeout), ("max_wait", max_wait)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_wait = max_wait
        self._open = opener
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get(self, url: str, params: dict) -> dict:
        request = Request(url + "?" + urlencode(params), headers={
            "Accept": "application/json", "User-Agent": "weather-rpa/0.1",
        })
        for attempt in range(self.max_attempts):
            delay = min(2 ** attempt, self.max_wait)
            try:
                with self._open(request, timeout=self.timeout) as response:
                    data = response.read()
            except HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                exc.close()
                if status not in (429, 500, 502, 503, 504) or attempt + 1 == self.max_attempts:
                    raise OpenMeteoError(f"Open-Meteo HTTP {status}") from exc
                if retry_after:
                    delay = self._retry_delay(retry_after, delay)
            except (URLError, TimeoutError, ConnectionError, HTTPException) as exc:
                if attempt + 1 == self.max_attempts:
                    raise OpenMeteoError("Open-Meteo request failed after bounded retries") from exc
            else:
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeError) as exc:
                    raise OpenMeteoError("Open-Meteo returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise OpenMeteoError("Open-Meteo response must be a JSON object")
                if payload.get("error"):
                    raise OpenMeteoError("Open-Meteo reported an API error")
                return payload
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
            raise OpenMeteoError("Retry-After exceeds configured wait limit")
        return max(fallback, delay)
