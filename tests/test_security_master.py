import sys
from pathlib import Path
from decimal import Decimal
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from market_pipeline.security_master import SecurityAlias, SecurityMaster
from market_pipeline.corporate_actions import StockSplit, adjust_ohlcv, reconcile_splits, validate_splits


def alias(ticker, start, end=None, known='2026-01-01T00:00:00Z', sid='S1', exchange='NASDAQ'):
    return SecurityAlias(sid, ticker, exchange, start, end, known, 'synthetic')


def split(ratio='4', known='2026-01-01T00:00:00Z', date='2026-06-01', sid='S1'):
    return StockSplit(sid, date, ratio, '1', known, 'synthetic')


def bars():
    return [dict(security_id='S1', date='2026-05-29', open='100', high='110', low='90', close='100', volume='200', adjustment_basis='raw')]


def test_ticker_change_effective_date():
    master = SecurityMaster([alias('OLD', '2025-01-01', '2026-06-01'), alias('NEW', '2026-06-01')])
    assert master.resolve('OLD', 'NASDAQ', '2026-05-31', '2026-06-02T00:00:00Z') == 'S1'
    assert master.resolve('OLD', 'NASDAQ', '2026-06-01', '2026-06-02T00:00:00Z') is None
    assert master.resolve('NEW', 'NASDAQ', '2026-06-01', '2026-06-02T00:00:00Z') == 'S1'


def test_late_mapping_does_not_leak():
    master = SecurityMaster([alias('ABC', '2025-01-01', known='2026-06-02T00:00:00Z')])
    assert master.resolve('ABC', 'NASDAQ', '2026-05-01', '2026-06-01T00:00:00Z') is None


def test_ticker_reuse_other_security():
    master = SecurityMaster([alias('ABC', '2025-01-01', '2026-01-01'), alias('ABC', '2026-01-01', sid='S2')])
    assert master.resolve('ABC', 'NASDAQ', '2026-02-01', '2026-04-01T00:00:00Z') == 'S2'


def test_overlapping_alias_rejected():
    with pytest.raises(ValueError, match='overlapping'):
        SecurityMaster([alias('ABC', '2025-01-01'), alias('ABC', '2026-01-01', sid='S2')])


def test_four_for_one_split():
    original = bars()
    out = adjust_ohlcv(original, [split()], '2026-07-01T00:00:00Z', '2026-06-30')[0]
    assert out['close'] == '25' and out['volume'] == '800' and out['split_factor'] == '4'
    assert original[0]['close'] == '100'


def test_split_lookahead_guard():
    out = adjust_ohlcv(bars(), [split(known='2026-07-01T00:00:00Z')], '2026-06-15T00:00:00Z', '2026-06-30')[0]
    assert out['close'] == '100' and out['split_factor'] == '1'


def test_split_effective_date_guard():
    out = adjust_ohlcv(bars(), [split()], '2026-06-01T00:00:00Z', '2026-05-31')[0]
    assert out['close'] == '100'


def test_prevent_double_adjustment():
    row = bars()[0]
    row['adjustment_basis'] = 'split-adjusted'
    with pytest.raises(ValueError, match='raw'):
        adjust_ohlcv([row], [split()], '2026-07-01T00:00:00Z', '2026-07-01')


def test_conflicting_splits_quarantined():
    assert validate_splits([split('4'), split('5')])
    with pytest.raises(ValueError, match='duplicate'):
        adjust_ohlcv(bars(), [split('4'), split('5')], '2026-07-01T00:00:00Z', '2026-07-01')


def test_cross_provider_reconciliation():
    status = reconcile_splits([split('4')], [split('5')])
    assert status[0]['status'] == 'ratio_mismatch'
    assert reconcile_splits([split('4')], [split('4')])[0]['status'] == 'matched'


def test_invalid_ratio():
    with pytest.raises(ValueError, match='positive'):
        split('0')


def test_timezones_required():
    with pytest.raises(ValueError, match='timezone'):
        split(known='2026-06-01T00:00:00')
