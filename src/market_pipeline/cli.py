"""Offline CLI for synthetic fixture demonstration."""
import argparse
import json
from pathlib import Path
from .core import load_bars, validate_bars, as_of_bars
from .extraction import extract_net_bookings


def main():
    parser = argparse.ArgumentParser(description="Market data DQ and PIT prototype")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--filing", required=True)
    parser.add_argument("--as-of", required=True, help="ISO 8601 timestamp with timezone")
    args = parser.parse_args()
    rows = load_bars(args.bars)
    errors = validate_bars(rows)
    if errors:
        parser.error("Quality gates failed: " + "; ".join(errors))
    report = {"input_rows": len(rows), "as_of_rows": len(as_of_bars(rows, args.as_of)),
              "extraction": extract_net_bookings(Path(args.filing).read_text(encoding="utf-8"))}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
