# Phase 3: Point-in-time Security Master & Corporate Actions

Offline, deterministic research prototype using synthetic fixtures. No authoritative production security master and no live corporate-action feed yet.

## Features
- `SecurityMaster.resolve(ticker, exchange, traded_on, as_of)`: stable internal security ID with effective dates, knowledge timestamp, half-open validity, ticker reuse and strict overlap rejection.
- `adjust_ohlcv(bars, actions, as_of, reference_date)`: forward split-equivalent prices and volumes, with individual action evidence and no look-ahead; raw inputs only.
- `reconcile_splits(primary, secondary)`: detect missing actions or disagreement in vendor split ratios; duplicate actions rejected.
- Input market bars require `security_id` for split processing. Do not join corporate actions by ticker alone.

## Limitations
- No historical correction/version supersession for conflicting alias assertions; overlapping mappings raise errors.
- Split-only adjustment, not dividend-adjusted or total return; no reverse merges, spin-offs, symbol changes auto-ingested, ADR ratios or entitlement handling.
- `known_at` is supplied by the data producer; it must be captured reliably at ingestion. Availability of historical feed data cannot be assumed retrospectively.
- The split adjustment is a research reference-date view. For a realistic as-of historical strategy, pass the actual decision timestamp and never use later known actions.

## Run
`python -m pip install -e '.[dev]' && python -m pytest -q`

Place these files in the existing repo without replacing Phase 1/2 modules. Phase 2 SEC ingestion, if not yet committed, must be merged separately.
