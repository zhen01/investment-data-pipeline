"""SEC submissions ingestion CLI. Requires a declared SEC User-Agent."""
import argparse
import json
import os
from .edgar import EdgarClient, ImmutableRawStore, RateLimiter


def main():
    parser = argparse.ArgumentParser(description="Fetch SEC submissions with content-addressed raw snapshots")
    parser.add_argument("--cik", required=True, help="SEC Central Index Key (1-10 digits)")
    parser.add_argument("--raw-dir", default="data/raw", help="Local raw snapshot directory")
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"), help="Identity with contact email (or SEC_USER_AGENT)")
    parser.add_argument("--rate", type=float, default=5.0, help="Process-local requests/sec, <=10 (default 5)")
    args = parser.parse_args()
    if not args.user_agent:
        parser.error("Set SEC_USER_AGENT or --user-agent to an identifying name and contact email")
    client = EdgarClient(args.user_agent, limiter=RateLimiter(args.rate))
    manifest = ImmutableRawStore(args.raw_dir).save(client.submissions(args.cik))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
