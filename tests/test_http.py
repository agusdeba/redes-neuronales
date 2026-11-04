"""Cliente HTTP: cache, reintentos con Retry-After, deteccion de desafio y circuit breaker (sin red)."""
import pytest
import requests

from src.common import http


class FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300


class FakeSession(requests.Session):
    def __init__(self, script):
        super().__init__()
        self.script, self.calls = list(script), []

    def request(self, method, url, **kw):
        self.calls.append(url)
        return self.script.pop(0)

    def get(self, url, **kw):  # robots.txt
        return FakeResp(404)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    http.PoliteClient._robots.clear()


def client(name, script):
    c = http.PoliteClient(name, session=FakeSession(script))
    c.cfg.update(rate=0, jitter=0, backoff_base=0.01, max_retries=3, breaker=3)
    return c


def test_cache_and_idempotency():
    c = client("statsbomb", [FakeResp(200, '{"a": 1}')])
    r1 = c.get("https://example.org/x.json")
    r2 = c.get("https://example.org/x.json")
    assert r1.json() == {"a": 1} and r2.from_cache and len(c.session.calls) == 1
    assert r1.provenance()["source_url"] == "https://example.org/x.json"


def test_retry_after_then_ok():
    c = client("rsssf", [FakeResp(429, "", {"Retry-After": "1"}), FakeResp(503), FakeResp(200, "ok")])
    r = c.get("https://example.org/retry")
    assert r.text == "ok" and len(c.session.calls) == 3


def test_challenge_marks_source_blocked_and_does_not_retry():
    c = client("soccerway", [FakeResp(403, "<html>Just a moment...<div class='cf-chl-widget'></div></html>")])
    with pytest.raises(http.SourceBlocked):
        c.get("https://example.org/cf")
    assert len(c.session.calls) == 1
    with pytest.raises(http.SourceBlocked):  # queda bloqueada para siguientes llamadas
        c.get("https://example.org/other")
    http.manifest().set_source_state("soccerway", "ok", 0)


def test_404_is_cached_as_not_found():
    c = client("nft", [FakeResp(404, "nope")])
    assert c.get("https://example.org/missing").status == 404
    assert c.get("https://example.org/missing").from_cache


def test_circuit_breaker():
    c = client("worldfootball", [FakeResp(500, "x")] * 20)
    with pytest.raises((requests.RequestException, http.SourceDown)):
        c.get("https://example.org/a")
    with pytest.raises((requests.RequestException, http.SourceDown)):
        c.get("https://example.org/b")
    with pytest.raises(http.SourceDown):
        c.get("https://example.org/c")
        c.get("https://example.org/d")
    http.manifest().set_source_state("worldfootball", "ok", 0)


def test_offline_mode_never_hits_network():
    c = http.PoliteClient("espn", offline=True, session=FakeSession([]))
    with pytest.raises(FileNotFoundError):
        c.get("https://example.org/nocache")
