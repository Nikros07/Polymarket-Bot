"""
Schlanker HTTP-Client für öffentliche JSON-APIs (nur lesend, Standardbibliothek).

Verhalten:
- Drosselung: zwischen dem Start zweier Anfragen liegen mindestens `min_interval_s`.
- Wiederholung bei Netzwerkfehlern, HTTP 429 und HTTP 5xx mit Backoff 1, 2, 4 ... s.
- Andere HTTP-4xx und ungültiges JSON scheitern sofort mit DataError.
- Zertifikate werden IMMER geprüft. Mit truststore nutzt Python den Zertifikatsspeicher des Betriebssystems.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlencode

from paperbot.data.base import DataError

try:  # Zertifikate aus dem OS-Speicher; Prüfung bleibt aktiv.
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

DEFAULT_USER_AGENT = "paperbot/0.1 (paper-trading research)"


def _encode_params(params: Optional[Dict[str, Any]]) -> str:
    """Query-String. None-Werte fallen weg, Booleans werden zu true/false."""
    if not params:
        return ""
    pairs = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        pairs.append((key, value))
    return urlencode(pairs)


class HttpClient:
    def __init__(
        self,
        base_url: str,
        min_interval_s: float = 0.15,
        timeout_s: float = 15.0,
        retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url
        self._min_interval = float(min_interval_s)
        self._timeout = float(timeout_s)
        self._retries = int(retries)
        self._user_agent = user_agent
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_start: Optional[float] = None

    def _url(self, path: str, params: Optional[Dict[str, Any]]) -> str:
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        query = _encode_params(params)
        return f"{url}?{query}" if query else url

    def _throttle(self) -> None:
        """Wartet, bis seit dem Start der letzten Anfrage min_interval_s vergangen sind."""
        if self._last_start is not None:
            wait = self._min_interval - (self._monotonic() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._monotonic()

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path, params)
        attempts = self._retries + 1
        last_error = ""
        for attempt in range(attempts):
            if attempt > 0:
                self._sleep(float(2 ** (attempt - 1)))
            self._throttle()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    body = response.read()
            except urllib.error.HTTPError as exc:  # vor URLError, da Unterklasse
                if exc.code == 429 or exc.code >= 500:
                    last_error = f"HTTP {exc.code} bei {url}"
                    continue
                raise DataError(f"HTTP {exc.code} bei {url}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                reason = getattr(exc, "reason", exc)
                last_error = f"Netzwerkfehler bei {url}: {reason}"
                continue
            try:
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise DataError(f"ungültiges JSON von {url}") from None
        raise DataError(f"{last_error} (nach {attempts} Versuchen)")
