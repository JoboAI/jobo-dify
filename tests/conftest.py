"""Shared test helpers. Every HTTP call is answered by a mock: nothing here uses the network."""

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

KEY = "jbe_live_unit_test_key_0000"
JOB_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

JOB: Dict[str, Any] = {
    "id": JOB_ID,
    "title": "Senior Backend Engineer",
    "company": {"id": "c1", "name": "Acme", "industries": ["Software"]},
    "locations": [{"location": "Berlin, Germany"}],
    "workplace_type": "Remote",
    "employment_type": "Full-time",
    "experience_level": "Senior",
    "compensation": {"min": 90000, "max": 120000, "currency": "USD", "period": "yearly"},
    "date_posted": "2026-11-01T00:00:00Z",
    "listing_url": "https://jobs.example.com/1",
    "apply_url": "https://jobs.example.com/1/apply",
    "source": "greenhouse",
    "summary": "Build APIs.",
    "description": "Full employer description.",
}

Handler = Callable[[httpx.Request], httpx.Response]


class Mock:
    """A mock Jobo API: records every request and answers with `handler`."""

    def __init__(self, handler: Handler) -> None:
        self.requests: List[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        self.transport = httpx.MockTransport(record)
        self.client = httpx.Client(transport=self.transport)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def body(self) -> Dict[str, Any]:
        return json.loads(self.last.content)


def reply(status: int, body: Any = None, headers: Optional[Dict[str, str]] = None) -> Handler:
    return lambda _request: httpx.Response(status, json=body, headers=headers)


@pytest.fixture
def api(monkeypatch):
    """
    Route every `httpx.Client()` the plugin creates to a mock.

    Usage: `mock = api(reply(200, {...}))`, then run a tool or the provider.
    """
    real_client = httpx.Client

    def install(handler: Handler) -> Mock:
        mock = Mock(handler)
        monkeypatch.setattr(
            "jobo_client.client.httpx.Client",
            lambda *a, **k: real_client(transport=mock.transport),
        )
        return mock

    return install


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries must not slow the tests down."""
    monkeypatch.setattr("jobo_client.client.time.sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def empty_taxonomy_cache(monkeypatch):
    """The occupation cache lives for the process: start each test without it."""
    monkeypatch.setattr("jobo_client.service._TAXONOMY_CACHE", {})
