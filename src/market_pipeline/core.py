"""Deterministic ingestion, data-quality checks and point-in-time logic."""
import csv
from datetime import datetime
from pathlib import Path

REQUIRED = {"ticker", "date", "open", "high", "low", "close", "volume", "available_at", "adjustment_basis"}


def load_bars(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError(f"Missing required columns: {sorted(REQUIRED - set(reader.fieldnames or []))}")
        return list(reader)


def validate_bars(rows):
    """Return explicit quality errors. Never silently remove bad records."""
    errors = []
    keys = set()
    for index, row in enumerate(rows, 1):
        prefix = f"row {index}"
        try:
            ticker = row["ticker"].strip()
            if not ticker:
                raise ValueError("empty ticker")
            day = datetime.strptime(row["date"], "%Y-%m-%d").date()
            available = datetime.fromisoformat(row["available_at"].replace("Z", "+00:00"))
            if available.tzinfo is None:
                raise ValueError("available_at must contain timezone")
            if available.date() < day:
                raise ValueError("available_at before market date")
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            volume = int(row["volume"])
            if min(o, h, l, c) <= 0 or volume < 0 or h < max(o, c, l) or l > min(o, c, h):
                raise ValueError("invalid price/volume/OHLC invariant")
            if row["adjustment_basis"] != "raw":
                raise ValueError("unsupported adjustment basis (expected raw)")
            key = ticker, day
            if key in keys:
                raise ValueError("duplicate ticker/date")
            keys.add(key)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{prefix}: {exc}")
    return errors


def as_of_bars(rows, timestamp):
    decision = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if decision.tzinfo is None:
        raise ValueError("as-of timestamp must contain timezone")
    return [row for row in rows if datetime.fromisoformat(row["available_at"].replace("Z", "+00:00")) <= decision]
