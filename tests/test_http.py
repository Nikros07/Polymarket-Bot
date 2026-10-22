"""Tests für paperbot.data.http. Laufen offline: urlopen wird durch Fakes ersetzt."""
from __future__ import annotations

import itertools
import urllib.error
import urllib.request
from typing import Any, List

import pytest

from paperbot.data.base import DataError
from paperbot.data.http import HttpClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeUrlopen:
    """Liefert der Reihe nach Antworten oder wirft Ausnahmen und protokolliert Anfragen."""

    def __init__(self, script: List[Any]) -> None:
        self.script = list(script)
        self.requests: List[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> FakeResponse:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def http_error(code: int, url: str = "https://api.example.com/x") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"status {code}", None, None)


def auto_clock():
    """Monotone Uhr, die bei jedem Aufruf 10 s weiterläuft. Drosselung greift dann nie."""
    counter = itertools.count()
    return lambda: next(counter) * 10.0


@pytest.fixture
def sleeps() -> List[float]:
    return []


@pytest.fixture
def patch_urlopen(monkeypatch):
    def install(script: List[Any]) -> FakeUrlopen:
        fake = FakeUrlopen(script)
        monkeypatch.setattr("paperbot.data.http.urllib.request.urlopen", fake)
        return fake

    return install


def make_client(sleeps: List[float], **kwargs: Any) -> HttpClient:
    kwargs.setdefault("monotonic", auto_clock())
    return HttpClient("https://api.example.com/", sleep=sleeps.append, **kwargs)


def test_success_returns_parsed_json_and_encodes_params(patch_urlopen, sleeps):
    fake = patch_urlopen([FakeResponse(b'{"a": 1, "b": [true]}')])
    client = make_client(sleeps)

    result = client.get_json(
        "/markets/",
        params={"limit": 5, "active": True, "closed": False, "tag": None, "q": "a b"},
    )

    assert result == {"a": 1, "b": [True]}
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req.full_url == "https://api.example.com/markets/?limit=5&active=true&closed=false&q=a+b"
    assert req.get_header("User-agent") == "paperbot/0.1 (paper-trading research)"
    assert req.get_header("Accept") == "application/json"
    assert sleeps == []


@pytest.mark.parametrize(
    "base, path, expected",
    [
        ("https://api.example.com", "markets", "https://api.example.com/markets"),
        ("https://api.example.com/", "/markets", "https://api.example.com/markets"),
    ],
)
def test_url_joins_base_and_path_without_double_slashes(patch_urlopen, sleeps, base, path, expected):
    fake = patch_urlopen([FakeResponse(b"[]")])
    HttpClient(base, sleep=sleeps.append, monotonic=auto_clock()).get_json(path)
    assert fake.requests[0].full_url == expected


def test_429_then_success_sleeps_one_second(patch_urlopen, sleeps):
    fake = patch_urlopen([http_error(429), FakeResponse(b"{}")])
    client = make_client(sleeps)

    assert client.get_json("/x") == {}
    assert len(fake.requests) == 2
    assert sleeps == [1.0]


def test_500_three_times_raises_data_error(patch_urlopen, sleeps):
    fake = patch_urlopen([http_error(500), http_error(502), http_error(503), http_error(500)])
    client = make_client(sleeps)

    with pytest.raises(DataError) as info:
        client.get_json("/x")

    assert len(fake.requests) == 4  # 1 Versuch + 3 Wiederholungen
    assert sleeps == [1.0, 2.0, 4.0]
    assert "500" in str(info.value)
    assert "https://api.example.com/x" in str(info.value)


def test_404_raises_immediately_without_retry(patch_urlopen, sleeps):
    fake = patch_urlopen([http_error(404)])
    client = make_client(sleeps)

    with pytest.raises(DataError, match="404"):
        client.get_json("/x")

    assert len(fake.requests) == 1
    assert sleeps == []


def test_network_error_is_retried(patch_urlopen, sleeps):
    fake = patch_urlopen([urllib.error.URLError("boom"), urllib.error.URLError("boom"), FakeResponse(b"[1]")])
    client = make_client(sleeps)

    assert client.get_json("/x") == [1]
    assert len(fake.requests) == 3
    assert sleeps == [1.0, 2.0]


def test_invalid_json_raises_data_error_without_retry(patch_urlopen, sleeps):
    fake = patch_urlopen([FakeResponse(b"<html>nope</html>")])
    client = make_client(sleeps)

    with pytest.raises(DataError, match="ungültiges JSON"):
        client.get_json("/x")

    assert len(fake.requests) == 1
    assert sleeps == []


def test_throttle_sleeps_for_remaining_interval(patch_urlopen, sleeps):
    fake = patch_urlopen([FakeResponse(b"1"), FakeResponse(b"2"), FakeResponse(b"3")])
    now = {"t": 100.0}
    client = HttpClient(
        "https://api.example.com",
        min_interval_s=0.15,
        sleep=sleeps.append,
        monotonic=lambda: now["t"],
    )

    client.get_json("/a")          # Start bei t=100.00, kein Warten
    now["t"] = 100.05
    client.get_json("/b")          # 0.05 s nach dem letzten Start -> 0.10 s Warten
    assert sleeps == [pytest.approx(0.10)]

    now["t"] = 101.0
    client.get_json("/c")          # Abstand groß genug -> kein weiteres Warten
    assert sleeps == [pytest.approx(0.10)]
    assert len(fake.requests) == 3
