"""SQLite-backed, reproducible research lineage and idempotent materialization.

A local prototype: SQLite transactions ensure consistency, not distributed coordination.
Raw payloads remain in the append-only-by-convention object store in edgar.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .security_master import SecurityAlias, SecurityMaster
from .corporate_actions import StockSplit, adjust_ohlcv, validate_splits

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS raw_observations (
 observation_id TEXT PRIMARY KEY,
 source_url TEXT NOT NULL,
 fetched_at TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 object_path TEXT NOT NULL,
 manifest_path TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY,
 as_of TEXT NOT NULL,
 reference_date TEXT NOT NULL,
 input_digest TEXT NOT NULL,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('complete', 'failed')),
 row_count INTEGER NOT NULL CHECK(row_count>=0),
 unresolved_count INTEGER NOT NULL CHECK(unresolved_count>=0),
 error_count INTEGER NOT NULL CHECK(error_count>=0)
);
CREATE TABLE IF NOT EXISTS adjusted_bars (
 run_id TEXT NOT NULL REFERENCES runs(run_id),
 security_id TEXT NOT NULL,
 ticker TEXT NOT NULL,
 exchange TEXT NOT NULL,
 trade_date TEXT NOT NULL,
 adjusted_payload TEXT NOT NULL,
 PRIMARY KEY(run_id,security_id,trade_date)
);
CREATE TABLE IF NOT EXISTS lineage (
 run_id TEXT NOT NULL REFERENCES runs(run_id),
 security_id TEXT NOT NULL,
 trade_date TEXT NOT NULL,
 input_digest TEXT NOT NULL,
 as_of TEXT NOT NULL,
 transformation TEXT NOT NULL,
 PRIMARY KEY(run_id,security_id,trade_date)
);
CREATE INDEX IF NOT EXISTS idx_bars_security_day ON adjusted_bars(security_id,trade_date);
"""


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(obj):
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("as_of must be timezone aware")
    return result.astimezone(timezone.utc).isoformat()


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def register_raw_observation(conn, store_root, manifest_path):
    """Verify on-disk bytes before registering provenance. No raw content is mutated."""
    root = Path(store_root).resolve()
    path = Path(manifest_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("manifest must be within store root")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {"source_url", "fetched_at", "sha256", "object_path"}
    if not required.issubset(manifest):
        raise ValueError("incomplete provenance manifest")
    blob = (root / manifest["object_path"]).resolve()
    if not blob.is_relative_to(root):
        raise ValueError("unsafe object path")
    content = blob.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        raise ValueError("raw blob hash mismatch")
    observation_id = hashlib.sha256(path.read_bytes()).hexdigest()
    conn.execute("INSERT OR IGNORE INTO raw_observations VALUES (?,?,?,?,?,?,?)", (
        observation_id, manifest["source_url"], manifest["fetched_at"],
        manifest["sha256"], manifest["object_path"], str(path.relative_to(root)),
        datetime.now(timezone.utc).isoformat()))
    return observation_id


def materialize_bars(conn, bars: Iterable[dict], aliases: Iterable[SecurityAlias],
                     splits: Iterable[StockSplit], *, as_of: str, reference_date: str,
                     strict: bool = True):
    """PIT-resolve and adjust raw bars; commit a complete run atomically.

    Input identity is independent of row ordering. Conflicting duplicates are errors.
    Strict mode rejects unresolved tickers and invalid rows with no partial writes.
    Non-strict mode skips unresolved mappings and reports count (never silently drops).
    """
    from .core import validate_bars
    bars = list(bars)
    aliases, splits = list(aliases), list(splits)
    cutoff = _utc(as_of)
    if validate_splits(splits):
        raise ValueError("invalid split feed: " + "; ".join(validate_splits(splits)))
    master = SecurityMaster(aliases)
    errors = validate_bars(bars)
    if errors:
        raise ValueError("market data quality gates failed: " + "; ".join(errors))
    if any(_utc(row["available_at"]) > cutoff for row in bars):
        raise ValueError("input includes bars unavailable at as_of; filter upstream")
    from datetime import date
    ref = date.fromisoformat(reference_date)
    if ref > datetime.fromisoformat(cutoff).date():
        raise ValueError("reference_date cannot be after as_of date")
    prepared = []
    for row in bars:
        if date.fromisoformat(row["date"]) > ref:
            raise ValueError("bar is later than reference_date")
        prepared.append(dict(row))
    # Ensure deterministic run IDs regardless of vendor row ordering.
    payload = {"bars": sorted(prepared, key=canonical_json),
               "aliases": sorted([a.__dict__ for a in aliases], key=canonical_json),
               "splits": sorted([a.__dict__ for a in splits], key=canonical_json),
               "as_of": cutoff, "reference_date": reference_date, "schema_version": 1}
    input_digest = digest(payload)
    run_id = input_digest
    existing = conn.execute("SELECT run_id, row_count, unresolved_count FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if existing:
        return {"run_id": run_id, "status": "already_materialized", "row_count": existing[1], "unresolved_count": existing[2]}
    unresolved, resolved = 0, []
    for row in prepared:
        sid = master.resolve(row["ticker"], row.get("exchange", ""), row["date"], cutoff)
        if sid is None:
            unresolved += 1
            if strict:
                raise ValueError(f"unresolved ticker {row['ticker']} / {row.get('exchange','')} on {row['date']}")
            continue
        resolved.append({**row, "security_id": sid})
    adjusted = adjust_ohlcv(resolved, splits, cutoff, ref)
    keys = [(r["security_id"], r["date"]) for r in adjusted]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate security_id/date after identifier resolution")
    # Transaction: no partial runs on key collisions, failures or invalid adjustments.
    with conn:
        conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", (
            run_id, cutoff, reference_date, input_digest, datetime.now(timezone.utc).isoformat(),
            "complete", len(adjusted), unresolved, 0))
        for row in adjusted:
            conn.execute("INSERT INTO adjusted_bars VALUES (?,?,?,?,?,?)", (
                run_id, row["security_id"], row["ticker"], row["exchange"],
                row["date"], canonical_json(row)))
            conn.execute("INSERT INTO lineage VALUES (?,?,?,?,?,?)", (
                run_id, row["security_id"], row["date"], digest(next(
                    x for x in resolved if x["security_id"] == row["security_id"] and x["date"] == row["date"])),
                cutoff, "PIT alias resolution + split-adjusted-to-reference/v1"))
    return {"run_id": run_id, "status": "complete", "row_count": len(adjusted), "unresolved_count": unresolved}


def quality_metrics(conn, run_id):
    run = conn.execute("SELECT row_count, unresolved_count, error_count FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("unknown run")
    rows, unresolved, errors = run
    total = rows + unresolved
    return {"run_id": run_id, "rows_materialized": rows,
            "unresolved_identifiers": unresolved, "dq_errors": errors,
            "identifier_resolution_rate": rows / total if total else None,
            "lineage_rows": conn.execute("SELECT COUNT(*) FROM lineage WHERE run_id=?", (run_id,)).fetchone()[0]}
