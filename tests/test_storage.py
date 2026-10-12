import json
from pathlib import Path
import pytest
from market_pipeline.storage import connect, materialize_bars, quality_metrics, register_raw_observation
from market_pipeline.security_master import SecurityAlias
from market_pipeline.corporate_actions import StockSplit


def inputs():
    bars = [dict(ticker='OLD', exchange='XNYS', date='2026-01-02', open='100', high='110', low='90', close='102', volume='200', available_at='2026-01-03T12:00:00Z', adjustment_basis='raw')]
    aliases = [SecurityAlias('SEC1', 'OLD', 'XNYS', '2020-01-01', '2026-02-01', '2020-01-02T00:00:00Z', 'vendor'), SecurityAlias('SEC1', 'NEW', 'XNYS', '2026-02-01', None, '2026-01-25T00:00:00Z', 'vendor')]
    splits = [StockSplit('SEC1', '2026-01-15', '4', '1', '2026-01-10T00:00:00Z', 'vendor')]
    return bars, aliases, splits


def test_idempotent_and_lineage(tmp_path):
    bars, aliases, splits = inputs()
    with connect(tmp_path/'db.sqlite') as c:
        a = materialize_bars(c, bars, aliases, splits, as_of='2026-02-15T00:00:00Z', reference_date='2026-02-14')
        b = materialize_bars(c, list(reversed(bars)), aliases, splits, as_of='2026-02-15T00:00:00Z', reference_date='2026-02-14')
        assert a['run_id'] == b['run_id']
        assert b['status'] == 'already_materialized'
        row = json.loads(c.execute('SELECT adjusted_payload FROM adjusted_bars').fetchone()[0])
        assert row['close'] == '25.5' and row['volume'] == '800'
        assert quality_metrics(c, a['run_id'])['lineage_rows'] == 1
        assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1


def test_no_future_split(tmp_path):
    bars, aliases, splits = inputs()
    with connect(tmp_path/'db.sqlite') as c:
        out = materialize_bars(c, bars, aliases, splits, as_of='2026-01-08T00:00:00Z', reference_date='2026-01-07')
        row = json.loads(c.execute('SELECT adjusted_payload FROM adjusted_bars WHERE run_id=?', (out['run_id'],)).fetchone()[0])
        assert row['close'] == '102'


def test_unresolved_strict_rolls_back(tmp_path):
    bars, aliases, splits = inputs()
    with connect(tmp_path/'db.sqlite') as c:
        with pytest.raises(ValueError, match='unresolved'):
            materialize_bars(c, [{**bars[0], 'ticker':'MISSING'}], aliases, splits, as_of='2026-02-15T00:00:00Z', reference_date='2026-02-14')
        assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0


def test_unresolved_non_strict_metrics(tmp_path):
    bars, aliases, splits = inputs()
    with connect(tmp_path/'db.sqlite') as c:
        r = materialize_bars(c, [{**bars[0], 'ticker':'MISSING'}], aliases, splits, as_of='2026-02-15T00:00:00Z', reference_date='2026-02-14', strict=False)
        m = quality_metrics(c, r['run_id'])
        assert m['identifier_resolution_rate'] == 0 and m['unresolved_identifiers'] == 1


def test_dq_error_prevents_partial_materialization(tmp_path):
    bars, aliases, splits = inputs()
    with connect(tmp_path/'db.sqlite') as c:
        with pytest.raises(ValueError, match='quality'):
            materialize_bars(c, [{**bars[0], 'high':'1'}], aliases, splits, as_of='2026-02-15T00:00:00Z', reference_date='2026-02-14')
        assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0


def test_raw_manifest_hash_verification(tmp_path):
    root = tmp_path/'raw'; (root/'objects').mkdir(parents=True)
    import hashlib
    payload=b'{"cik":123}'
    sha=hashlib.sha256(payload).hexdigest()
    (root/'objects'/'blob').write_bytes(payload)
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps(dict(source_url='https://data.sec.gov/test',fetched_at='2026-01-01T00:00:00Z',sha256=sha,object_path='objects/blob')))
    with connect(tmp_path/'db.sqlite') as c:
        first=register_raw_observation(c,root,manifest)
        assert first==register_raw_observation(c,root,manifest)
        assert c.execute('SELECT COUNT(*) FROM raw_observations').fetchone()[0]==1
        (root/'objects'/'blob').write_bytes(b'tampered')
        with pytest.raises(ValueError,match='hash mismatch'):
            register_raw_observation(c,root,manifest)
