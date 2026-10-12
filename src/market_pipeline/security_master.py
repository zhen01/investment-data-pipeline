"""Point-in-time, effective-dated security identifiers.

`valid_from`/`valid_to` describe when a ticker referred to a security;
`known_at` describes when that mapping became available to researchers.
Half-open validity ranges prevent ambiguity at ticker transitions.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional


def _date(value):
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(value)


def _instant(value):
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('known_at / as_of requires a timezone')
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class SecurityAlias:
    security_id: str
    ticker: str
    exchange: str
    valid_from: date
    valid_to: Optional[date]
    known_at: datetime
    source: str

    def __post_init__(self):
        object.__setattr__(self, 'valid_from', _date(self.valid_from))
        if self.valid_to is not None:
            object.__setattr__(self, 'valid_to', _date(self.valid_to))
        object.__setattr__(self, 'known_at', _instant(self.known_at))
        for field in ('security_id', 'ticker', 'exchange', 'source'):
            if not getattr(self, field) or not getattr(self, field).strip():
                raise ValueError(f'{field} must be nonempty')
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError('valid_to must be after valid_from')


class SecurityMaster:
    def __init__(self, aliases):
        self.aliases = tuple(aliases)
        # Conflicting simultaneous mappings for the same ticker on an exchange
        # are rejected even if their knowledge timestamps differ. Historical
        # corrections need an explicitly versioned replacement in a later phase.
        for i, a in enumerate(self.aliases):
            for b in self.aliases[i + 1:]:
                if (a.ticker.upper(), a.exchange.upper()) != (b.ticker.upper(), b.exchange.upper()):
                    continue
                a_end = a.valid_to or date.max
                b_end = b.valid_to or date.max
                if a.valid_from < b_end and b.valid_from < a_end:
                    raise ValueError(f'overlapping ticker/exchange validity: {a.ticker}/{a.exchange}')

    def resolve(self, ticker, exchange, traded_on, as_of):
        """Return unique security ID or None; never silently guess."""
        traded_on, as_of = _date(traded_on), _instant(as_of)
        matching = [a for a in self.aliases if a.ticker.upper() == ticker.upper()
                    and a.exchange.upper() == exchange.upper()
                    and a.valid_from <= traded_on
                    and (a.valid_to is None or traded_on < a.valid_to)
                    and a.known_at <= as_of]
        if len(matching) > 1:
            raise ValueError('ambiguous ticker resolution')
        return matching[0].security_id if matching else None
