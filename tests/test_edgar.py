"""All SEC ingestion tests are deterministic and network-free."""
import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from market_pipeline.edgar import (EdgarClient, FetchResult, ImmutableRawStore,
                                   RateLimiter, valid_cik)


class Response:
    status = 200
    headers = {"Content-Type": "application/json; charset=utf-8"}

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._payload


def test_cik_validation():
    assert valid_cik("320193") == "0000320193"
    with pytest.raises(ValueError):
        valid_cik("320193/../")


def test_rate_limiter_process_pacing():
    state = [0.0]
    delays = []
    def clock(): return state[0]
    def sleep(s):
        delays.append(s)
        state[0] += s
    limiter = RateLimiter(5, clock=clock, sleep=sleep)
    limiter.wait()
    limiter.wait()
    assert delays == [pytest.approx(.2)]
    with pytest.raises(ValueError):
        RateLimiter(11)


def test_request_identity_url_and_cik():
    requests = []
    def opener(request, timeout):
        requests.append(request)
        return Response(b'{"cik":320193,"filings":{"recent":{}}}')
    client = EdgarClient("Research Project contact@example.org", opener=opener)
    result = client.submissions(320193)
    assert result.source_url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert requests[0].get_header("User-agent") == "Research Project contact@example.org"
    assert result.payload.startswith(b'{"cik"')


def test_retry_after_429_and_recovery():
    attempts = [0]
    delays = []
    def opener(request, timeout):
        attempts[0] += 1
        if attempts[0] == 1:
            raise HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "2"}, None)
        return Response(b'{"cik":320193,"filings":{}}')
    result = EdgarClient("Research contact@example.org", opener=opener, sleep=delays.append).submissions(320193)
    assert result.status_code == 200
    assert attempts[0] == 2 and delays == [2.0]


def test_no_retry_on_404():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 404, "not found", {}, None)
    with pytest.raises(HTTPError):
        EdgarClient("Research contact@example.org", opener=opener).submissions(123)


def test_bad_schema_or_wrong_cik_rejected():
    for data in (b'{"cik":1,"filings":{}}', b'{"cik":320193}', b'not-json'):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            EdgarClient("Research contact@example.org", opener=lambda *_ , **__: Response(data)).submissions(320193)


def test_snapshot_idempotence_integrity_and_versions(tmp_path):
    store = ImmutableRawStore(tmp_path)
    first = FetchResult("https://data.sec.gov/example", b'{"v":1}', "2026-10-12T12:00:00+00:00", 200, "application/json")
    second = FetchResult(first.source_url, b'{"v":2}', "2026-10-12T13:00:00+00:00", 200, "application/json")
    m1 = store.save(first)
    assert store.save(first) == m1
    m2 = store.save(second)
    assert m1["sha256"] != m2["sha256"]
    assert store.verify(m1) and store.verify(m2)
    path = tmp_path / m1["object_path"]
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    assert not store.verify(m1)
    with pytest.raises(RuntimeError):
        store.save(first)
