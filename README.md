# Market Data Quality & AI Extraction Pipeline

**Status:** Working offline prototype, not a production market-data service. Created from the original Tower Research-oriented design notes. The sample data are synthetic.

## What works today

- CSV data-contract validation for ticker, prices, volume, adjustment basis and publication timestamp.
- Duplicate event detection and OHLC sanity checks.
- Point-in-time filtering on `available_at`, avoiding look-ahead from late-arriving events.
- Deterministic regex extraction of `net bookings` from text, with source evidence and explicit abstention.
- Seven automated pytest tests, including bad-feed failure injection.

## Quickstart (Python 3.10+)

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m market_pipeline.cli --bars examples/bars.csv --filing examples/filing.txt --as-of 2026-04-02T18:00:00+00:00
```

No API keys required for this prototype.

## Architecture

`Sample market CSV -> typed quality gates -> as-of filtering -> research-ready JSON`

`Sample disclosure text -> evidence-preserving regex baseline -> research-ready JSON`

## Planned (not yet implemented)

1. Immutable raw ingestion of SEC EDGAR and licensed market feeds with rate limiting.
2. Security master and corporate action reconciliations.
3. Structured LLM extraction with source-span evidence, abstention, human-review workflow, and evaluation against a labeled gold set.
4. SQL storage, lineage, idempotent backfills, CI, observability and measured quality KPIs.

**Important:** The extraction baseline is **not LLM-powered**. Results are not suitable for real investment decisions. This repo intentionally distinguishes implemented features from planned features.
