"""Offline reproducible SQLite backfill from JSON fixtures."""
import argparse
import json
from pathlib import Path

from .storage import connect, materialize_bars, quality_metrics, register_raw_observation
from .security_master import SecurityAlias
from .corporate_actions import StockSplit


def main():
    p = argparse.ArgumentParser(description="PIT SQLite materialization from validated fixture")
    p.add_argument("--input", required=True, help="JSON file with bars, aliases, splits")
    p.add_argument("--db", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--reference-date", required=True)
    p.add_argument("--allow-unresolved", action="store_true")
    p.add_argument("--raw-store", help="Existing immutable raw-object store root")
    p.add_argument("--manifest", action="append", default=[], help="Provenance manifest (repeatable)")
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.manifest and not args.raw_store:
        p.error("--manifest requires --raw-store")
    with connect(args.db) as conn:
        observations = [register_raw_observation(conn, args.raw_store, name) for name in args.manifest]
        result = materialize_bars(conn, data["bars"], [SecurityAlias(**a) for a in data["aliases"]],
            [StockSplit(**s) for s in data.get("splits", [])], as_of=args.as_of,
            reference_date=args.reference_date, strict=not args.allow_unresolved)
        result["quality"] = quality_metrics(conn, result["run_id"])
        result["raw_observation_ids"] = observations
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
