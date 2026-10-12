"""Evidence-linked regex extraction baseline; not an LLM."""
import re

_BOOKINGS = re.compile(r"net bookings\s+(?:were|of|totaled)\s+\$?([\d,.]+)\s*(million|billion)", re.I)


def extract_net_bookings(text):
    match = _BOOKINGS.search(text)
    if not match:
        return {"value_usd": None, "evidence": None, "method": "regex", "status": "abstained"}
    value = float(match.group(1).replace(",", "")) * (1_000_000_000 if match.group(2).lower() == "billion" else 1_000_000)
    return {"value_usd": value, "evidence": match.group(0), "method": "regex", "status": "extracted"}
