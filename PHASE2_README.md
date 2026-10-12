# Phase 2: SEC EDGAR ingestion

This patch adds `market_pipeline.edgar` and a separate `market_pipeline.edgar_cli` entry point. The existing offline demo and source files are not replaced.

## Installation and run

Copy `src/market_pipeline/edgar.py`, `src/market_pipeline/edgar_cli.py`, and `tests/test_edgar.py` into the corresponding paths of your repository, then:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
export SEC_USER_AGENT='Personal Investment Research your-real-contact@example.com'
python -m market_pipeline.edgar_cli --cik 0000320193 --raw-dir data/raw
```

The command downloads the latest SEC submissions JSON for the selected CIK and prints its manifest, SHA-256 digest, timestamps, and immutable relative object path. **Replace the example email with your real contact details.** The code does not connect to any licensed feed.

## Design decisions

- URL allowlisted by construction: `https://data.sec.gov/submissions/CIK##########.json`; strict CIK input validation.
- A declared SEC User-Agent, HTTP timeout, explicit JSON/schema/CIK checks, retryable 429/5xx and transient transport failures, Retry-After support.
- Conservative default of 5 requests/second; process-local limiter only. Respect SEC aggregate fair-access guidance across all processes and machines.
- Raw response bytes are content-addressed (`objects/sha256/...`), SHA-256 checksummed, and saved with `O_EXCL` on a local filesystem. Each distinct observation has a write-once manifest recording the fetch timestamp and origin.
- Identical bytes deduplicate; changed responses create new objects; historical versions are retained. A corrupted existing object fails the write.
- All tests are offline; 7 added tests passed in the authoring environment. No live SEC integration test has been run.

## Limitations / future work

- Local filesystem write-once-by-convention is **not** regulatory-grade immutability, object-lock/WORM, tamper-proof manifests, or a multi-process transaction protocol. Concurrent writers can observe partially written content; use atomic staging and durable object storage before production.
- `fetched_at` records the fetch observation time, **not** the SEC's first public dissemination timestamp. Point-in-time research must use filing acceptance/dissemination metadata and conservative availability conventions.
- Rate limiting is **not distributed**; multiple workers require a shared global limiter.
- A real backfill index and pagination, SQL lineage, security masters, corporate action reconciliation, licensed vendor ingestion, LLM extraction, human review and evaluation remain future work.
- No live investment decisions should rely on this educational prototype.

## SEC documentation

- https://www.sec.gov/about/developer-resources
- https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
