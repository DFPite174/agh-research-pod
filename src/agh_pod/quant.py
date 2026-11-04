"""Reviewed expanding-window forecasting recipe; no external code execution."""
from __future__ import annotations

import csv as csv_parser
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd


def load_dataset(manifest_path):
    path = Path(manifest_path).resolve()
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('quant manifest exceeds 1MB')
    manifest = json.loads(raw)
    required = ('csv', 'source', 'license', 'evidence_level', 'limitations')
    if not isinstance(manifest, dict) or any(not isinstance(manifest.get(k), str) or not manifest[k].strip() for k in required):
        raise ValueError('quant manifest requires csv, source, license, evidence_level, limitations')
    if manifest['evidence_level'] not in {'synthetic', 'alternative_real'}:
        raise ValueError('unknown quant evidence level')
    csv = (path.parent / manifest['csv']).resolve()
    if not csv.is_file() or csv.stat().st_size > 25_000_000:
        raise ValueError('quant CSV missing or exceeds 25MB')
    with csv.open('rb') as stream:
        content = stream.read(25_000_001)
    if len(content) > 25_000_000:
        raise ValueError('quant CSV exceeds 25MB')
    snapshot = {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                'csv_sha256': hashlib.sha256(content).hexdigest()}
    return manifest, raw, content, snapshot


def snapshot_dataset(manifest_path):
    return load_dataset(manifest_path)[3]


def validate_payload(payload):
    features = payload.get('features')
    if (not isinstance(features, list) or not 1 <= len(features) <= 30
            or any(not isinstance(v, str) or not v.strip() or v == 'date' for v in features)
            or len(set(features)) != len(features)):
        raise ValueError('quant requires 1..30 unique feature columns')
    if not isinstance(payload.get('target'), str) or not payload['target'].strip() or payload['target'] == 'date':
        raise ValueError('quant target column required')
    if not isinstance(payload.get('dataset'), str) or not payload['dataset'].strip():
        raise ValueError('quant dataset manifest required')
    n = payload.get('min_train', 36)
    penalty = payload.get('ridge', 1.0)
    if type(n) is not int or not 12 <= n <= 2000:
        raise ValueError('min_train must be 12..2000')
    if type(penalty) not in (float, int) or not np.isfinite(penalty) or not 0 < penalty <= 1e6:
        raise ValueError('ridge must be finite and positive, at most 1e6')


def execute_quant(payload, *, expected_snapshot=None):
    validate_payload(payload)
    manifest, _raw, content, snapshot = load_dataset(payload['dataset'])
    if expected_snapshot is not None and snapshot != expected_snapshot:
        from .workflow import IntegrityError
        raise IntegrityError('approved quant dataset changed before calculation')
    try:
        records = csv_parser.reader(io.StringIO(content.decode('utf-8-sig')), strict=True)
        header = next(records, [])
        if not header or len(header) != len(set(header)) or any(not h.strip() for h in header):
            raise ValueError('CSV column names must be nonempty and unique')
        count = 0
        for row in records:
            if not row:
                continue
            count += 1
            if len(row) != len(header):
                raise ValueError('CSV field count differs from header')
            if count > 5000:
                raise ValueError('CSV exceeds 5000 observations')
    except csv_parser.Error as exc:
        raise ValueError('malformed CSV records') from exc
    frame = pd.read_csv(io.BytesIO(content), index_col=False)
    cols = list(dict.fromkeys(payload['features'] + [payload['target']]))
    if 'date' not in frame or not set(cols).issubset(frame.columns):
        raise ValueError('CSV requires date and configured target/features')
    dates = pd.to_datetime(frame['date'], errors='raise')
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('dates must be unique, complete and strictly increasing')
    index = pd.DatetimeIndex(dates)
    if index.tz is not None or not (index == index.normalize()).all():
        raise ValueError('dates must be timezone-naive calendar dates without intraday timestamps')
    frequency = manifest.get('frequency')
    if frequency is not None:
        if frequency not in {'monthly', 'quarterly', 'daily'}:
            raise ValueError('frequency must be monthly, quarterly or daily')
        if frequency == 'daily':
            complete = (np.diff(index.asi8) == pd.Timedelta(days=1).value).all()
        else:
            periods = index.to_period('M' if frequency == 'monthly' else 'Q')
            complete = (np.diff(periods.asi8) == 1).all()
        if not complete:
            raise ValueError('declared calendar has duplicates or missing periods')
    availability = manifest.get('availability_column')
    if availability is not None:
        if not isinstance(availability, str) or availability not in frame:
            raise ValueError('availability column missing')
        available = pd.DatetimeIndex(pd.to_datetime(frame[availability], errors='raise'))
        if available.hasnans or available.tz is not None or (available > index).any():
            raise ValueError('values not available by declared row date')
    if len(frame) > 5000 or not np.isfinite(frame[cols].to_numpy(dtype=float)).all():
        raise ValueError('CSV must contain at most 5000 finite observations')
    # Every feature is lagged one observation. At t only targets through t-1 train.
    x = frame[payload['features']].to_numpy(dtype=float)[:-1]
    y = frame[payload['target']].to_numpy(dtype=float)[1:]
    start = payload.get('min_train', 36)
    if len(y) < start + 12:
        raise ValueError('at least 12 out-of-sample observations required')
    predictions = []
    for t in range(start, len(y)):
        train, targets = x[:t], y[:t]
        center, scale = train.mean(axis=0), train.std(axis=0)
        scale[scale == 0] = 1
        z = (train-center)/scale
        mean = targets.mean()
        beta = np.linalg.solve(z.T @ z + payload.get('ridge', 1.0)*np.eye(z.shape[1]), z.T @ (targets-mean))
        estimate = float(mean + ((x[t]-center)/scale) @ beta)
        predictions.append({'date': dates.iloc[t+1].isoformat(), 'actual': float(y[t]),
                            'forecast': estimate, 'baseline': float(mean),
                            'persistence': float(y[t-1]), 'train_count': t})
    mse = float(np.mean([(p['actual']-p['forecast'])**2 for p in predictions]))
    baseline = float(np.mean([(p['actual']-p['baseline'])**2 for p in predictions]))
    persistence = float(np.mean([(p['actual']-p['persistence'])**2 for p in predictions]))
    return {'execution_status': 'succeeded', 'evidence_level': manifest['evidence_level'],
            'research_status': 'not_evaluated' if manifest['evidence_level']=='synthetic' else 'local_adaptation',
            'method': 'one-observation-lag expanding-window ridge versus expanding historical mean and last observed value',
            'data_snapshot': snapshot, 'provenance': manifest, 'predictions': predictions,
            'data_qualification': {'frequency': frequency or 'unspecified_observation_step',
                                   'availability': 'declared_times_checked_not_provider_qualified' if availability else 'UNVERIFIED',
                                   'pit_certified': False},
            'metrics': {'n_oos': len(predictions), 'mse': mse, 'baseline_mse': baseline,
                        'oos_r2': 1-mse/baseline if baseline > 0 else None,
                        'persistence_mse': persistence,
                        'r2_vs_persistence': 1-mse/persistence if persistence > 0 else None},
            'limitations': [manifest['limitations'], 'One-step statistical forecast; not an executable trading backtest.',
                            'Release lags and revised vintages must be handled upstream; row dates alone do not establish PIT.',
                            'Repeated experiments can overfit; no automatic parameter search or profitability certification.']}
