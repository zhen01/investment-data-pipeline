"""Deterministic split normalization and provenance-aware reconciliation.

Only splits are supported. No dividend/total-return claim is made.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation


def _instant(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def _decimal(value):
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid decimal') from exc
    if not n.is_finite() or n <= 0:
        raise ValueError('value must be positive and finite')
    return n


@dataclass(frozen=True)
class StockSplit:
    security_id: str
    ex_date: date
    new_shares: Decimal
    old_shares: Decimal
    known_at: datetime
    source: str

    def __post_init__(self):
        object.__setattr__(self, 'ex_date', date.fromisoformat(self.ex_date) if isinstance(self.ex_date, str) else self.ex_date)
        object.__setattr__(self, 'new_shares', _decimal(self.new_shares))
        object.__setattr__(self, 'old_shares', _decimal(self.old_shares))
        object.__setattr__(self, 'known_at', _instant(self.known_at))
        if not self.security_id or not self.source:
            raise ValueError('security_id and source required')

    @property
    def ratio(self):
        return self.new_shares / self.old_shares


def validate_splits(actions):
    """Conflicting effective-date actions are quarantined, not netted."""
    errors, seen = [], {}
    for a in actions:
        key = (a.security_id, a.ex_date)
        if key in seen:
            errors.append(f'duplicate or conflicting split: {key}')
        seen[key] = a
    return errors


def adjust_ohlcv(bars, actions, as_of, reference_date):
    """Express prior raw OHLCV in split-equivalent units at reference_date.

    Only actions with bar_date < ex_date <= reference_date and known_at <= as_of
    qualify. This is a point-in-time research view, not vendor adjusted data.
    Never modifies input bars. Volumes are multiplied, prices divided.
    """
    if validate_splits(actions):
        raise ValueError('; '.join(validate_splits(actions)))
    cutoff = _instant(as_of)
    ref = date.fromisoformat(reference_date) if isinstance(reference_date, str) else reference_date
    result = []
    for bar in bars:
        day = date.fromisoformat(bar['date']) if isinstance(bar['date'], str) else bar['date']
        if day > ref:
            raise ValueError('bar occurs after reference_date')
        if bar.get('adjustment_basis') != 'raw':
            raise ValueError('only raw input bars accepted; prevent double adjustment')
        factor = Decimal('1')
        applied = []
        for a in actions:
            if a.security_id == bar['security_id'] and day < a.ex_date <= ref and a.known_at <= cutoff:
                factor *= a.ratio
                applied.append({'ex_date': a.ex_date.isoformat(), 'ratio': str(a.ratio), 'source': a.source})
        row = dict(bar)
        for field in ('open', 'high', 'low', 'close'):
            row[field] = str(_decimal(bar[field]) / factor)
        if 'volume' in bar:
            row['volume'] = str(_decimal(bar['volume']) * factor)
        row['adjustment_basis'] = 'split-adjusted-to-reference'
        row['split_factor'] = str(factor)
        row['applied_splits'] = applied
        result.append(row)
    return result


def reconcile_splits(primary, secondary):
    """Compare two providers' ratios by security and ex-date; report gaps."""
    if validate_splits(primary) or validate_splits(secondary):
        raise ValueError('duplicate split in provider input')
    a = {(x.security_id, x.ex_date): x.ratio for x in primary}
    b = {(x.security_id, x.ex_date): x.ratio for x in secondary}
    return [{'security_id': sid, 'ex_date': day.isoformat(),
             'status': ('missing_primary' if key not in a else
                        'missing_secondary' if key not in b else
                        'matched' if a[key] == b[key] else 'ratio_mismatch'),
             'primary_ratio': str(a[key]) if key in a else None,
             'secondary_ratio': str(b[key]) if key in b else None}
            for key in sorted(set(a) | set(b)) for sid, day in [key]]
