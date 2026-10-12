import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from market_pipeline.core import validate_bars, as_of_bars
from market_pipeline.extraction import extract_net_bookings


def bar(**kwargs):
    row = dict(ticker="TEST", date="2026-04-01", open="100", high="110", low="95", close="105", volume="1000", available_at="2026-04-02T12:00:00+00:00", adjustment_basis="raw")
    row.update(kwargs)
    return row


def test_valid_bar():
    assert validate_bars([bar()]) == []


def test_duplicate_vendor_retry():
    assert "duplicate" in validate_bars([bar(), bar()])[0]


def test_adjustment_basis_mismatch():
    assert "adjustment" in validate_bars([bar(adjustment_basis="split-adjusted")])[0]


def test_bad_ohlc():
    assert "OHLC" in validate_bars([bar(high="98")])[0]


def test_lookahead_exclusion():
    assert as_of_bars([bar()], "2026-04-02T11:59:59+00:00") == []
    assert len(as_of_bars([bar()], "2026-04-02T12:00:00+00:00")) == 1


def test_extract_provenance():
    result = extract_net_bookings("Synthetic report: Net bookings totaled $1.25 billion.")
    assert result["value_usd"] == 1_250_000_000
    assert "1.25 billion" in result["evidence"]


def test_abstain_when_no_evidence():
    assert extract_net_bookings("No figures disclosed.")["status"] == "abstained"
