"""Auditable SEC submissions ingestion. No network calls on import."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SEC_HOST = "https://data.sec.gov"
RETRYABLE = {429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_cik(cik: str | int) -> str:
    value = str(cik)
    if not re.fullmatch(r"\d{1,10}", value):
        raise ValueError("CIK must consist of 1-10 digits")
    return value.zfill(10)


class RateLimiter:
    """Process-local pacing; not a distributed/global SEC rate limiter."""

    def __init__(self, requests_per_second: float = 5.0, clock: Callable = time.monotonic, sleep: Callable = time.sleep):
        if not 0 < requests_per_second <= 10:
            raise ValueError("SEC fair-access rate must be in (0, 10]")
        self.interval = 1 / requests_per_second
        self.clock = clock
        self.sleep = sleep
        self.next_allowed = None

    def wait(self) -> None:
        now = self.clock()
        if self.next_allowed is not None and now < self.next_allowed:
            self.sleep(self.next_allowed - now)
            now = self.clock()
        self.next_allowed = now + self.interval


@dataclass(frozen=True)
class FetchResult:
    source_url: str
    payload: bytes
    fetched_at: str
    status_code: int
    content_type: str


class EdgarClient:
    def __init__(self, user_agent: str, *, limiter: RateLimiter | None = None, retries: int = 3,
                 timeout: float = 20, opener=None, sleep: Callable = time.sleep):
        if not user_agent or "@" not in user_agent or len(user_agent.strip()) < 12:
            raise ValueError("Pass an identifying SEC User-Agent including a real contact email")
        if retries < 0 or timeout <= 0:
            raise ValueError("Invalid retries or timeout")
        self.user_agent = user_agent.strip()
        self.limiter = limiter or RateLimiter()
        self.retries = retries
        self.timeout = timeout
        self.opener = opener or urlopen
        self.sleep = sleep

    def submissions(self, cik: str | int) -> FetchResult:
        url = f"{SEC_HOST}/submissions/CIK{valid_cik(cik)}.json"
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            req = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json", "Accept-Encoding": "identity"})
            try:
                with self.opener(req, timeout=self.timeout) as response:
                    status = response.status
                    if status != 200:
                        raise ValueError(f"Unexpected SEC response status: {status}")
                    content_type = response.headers.get("Content-Type", "")
                    if "json" not in content_type.lower():
                        raise ValueError(f"SEC returned non-JSON content type: {content_type}")
                    payload = response.read()
                    obj = json.loads(payload)
                    if not isinstance(obj, dict) or "cik" not in obj or "filings" not in obj:
                        raise ValueError("Unexpected SEC submissions schema")
                    if valid_cik(obj["cik"]) != valid_cik(cik):
                        raise ValueError("SEC response CIK does not match request")
                    return FetchResult(url, payload, utc_now(), status, content_type)
            except HTTPError as exc:
                if exc.code not in RETRYABLE or attempt == self.retries:
                    raise
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay(retry_after, attempt)
                self.sleep(delay)
            except (URLError, TimeoutError):
                if attempt == self.retries:
                    raise
                self.sleep(min(2 ** attempt, 30))
        raise AssertionError("Unreachable")


def _retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return min(max(0, float(value)), 60)
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
                return min(max(0, (dt - datetime.now(timezone.utc)).total_seconds()), 60)
            except (ValueError, TypeError, OverflowError):
                pass
    return min(2 ** attempt, 30)


class ImmutableRawStore:
    """Content-addressed bytes and a write-once provenance envelope per observation.

    Repeated identical bytes are deduplicated. Distinct observations always have
    distinct manifests. Filesystem storage is append-only by convention, not WORM.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def _create_once(path: Path, data: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        except FileExistsError:
            if path.read_bytes() != data:
                raise RuntimeError(f"Existing immutable object differs: {path}")
            return False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return True

    def save(self, fetched: FetchResult) -> dict:
        sha = hashlib.sha256(fetched.payload).hexdigest()
        blob = self.root / "objects" / "sha256" / sha[:2] / sha
        self._create_once(blob, fetched.payload)
        manifest = {"source_url": fetched.source_url, "fetched_at": fetched.fetched_at,
                    "status_code": fetched.status_code, "content_type": fetched.content_type,
                    "sha256": sha, "byte_length": len(fetched.payload),
                    "object_path": blob.relative_to(self.root).as_posix()}
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        mid = hashlib.sha256(encoded).hexdigest()
        record = self.root / "manifests" / mid[:2] / f"{mid}.json"
        self._create_once(record, encoded)
        return {**manifest, "manifest_path": record.relative_to(self.root).as_posix()}

    def verify(self, manifest: dict) -> bool:
        relative = Path(manifest["object_path"])
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            return False
        raw = path.read_bytes()
        return len(raw) == manifest["byte_length"] and hashlib.sha256(raw).hexdigest() == manifest["sha256"]
