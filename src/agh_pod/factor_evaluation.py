"""Estimate Table 3 alphas from supplied observations, never published targets.

Portfolio DatetimeIndex labels MUST be the actual holding month, not formation
month; callers must make that shift explicitly before calling. low_minus_high
is a decimal simple zero-cost return, so no second risk-free subtraction occurs.
Factor returns are decimal, monthly and already defined by their supplier. Exact
date labels must match; a superset factor calendar is explicitly sliced with
.loc. Missing months/values, duplicate columns and unidentified model definitions
fail without filling, interpolation or hidden sample deletion. Inference calls
empirical.factor_alpha with Newey-West lag 3 and its documented finite-sample
correction. Estimates do not certify source vintages, PIT integrity or tradability.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import empirical


FACTOR_COUNTS = {'Carhart4': 4, 'FF5': 5, 'HXZ4': 4, 'SY4': 4, 'DHS3': 3}


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _calendar(index):
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError('factor observations require a DatetimeIndex')
    if index.empty or index.hasnans or index.tz is not None or not (index == index.normalize()).all():
        raise ValueError('factor dates must be nonempty complete timezone-naive dates')
    periods = index.to_period('M')
    if periods.has_duplicates or not periods.is_monotonic_increasing:
        raise ValueError('factor dates must be unique monthly observations in increasing order')


def evaluate_factor_models(portfolios: dict[str, pd.DataFrame], factors: pd.DataFrame,
                           definitions: dict[str, list[str]]) -> dict:
    result = {'observed': {}, 'statistics': {}, 'errors': [], 'metadata': {
        'maxlags': 3, 'return_units': 'decimal monthly simple returns',
        'return_column': 'low_minus_high', 'risk_free_subtracted': False,
        'calendar': 'exact holding-month date labels; superset factor dates explicitly sliced',
        'split': 'pre2018: holding month before 2018-01; post2018: from 2018-01',
        'evidence': 'caller-supplied observations; provenance and paper-series equivalence unverified',
        'factor_definitions': {},
    }}

    def error(scope, message):
        result['errors'].append({'scope': scope, 'message': str(message)})

    if not isinstance(portfolios, dict) or not isinstance(definitions, dict):
        error('inputs', 'portfolios and factor definitions must be dictionaries')
        return result
    try:
        if not isinstance(factors, pd.DataFrame) or factors.columns.has_duplicates:
            raise ValueError('factors must be a DataFrame with unique columns')
        _calendar(factors.index)
    except ValueError as exc:
        error('factors', exc)
        return result
    for name, columns in definitions.items():
        if name not in FACTOR_COUNTS:
            error('definitions', 'unknown factor model name')
        elif (not isinstance(columns, list) or len(columns) != FACTOR_COUNTS[name]
              or any(not isinstance(column, str) or not column.strip() or column == 'const' for column in columns)
              or len(set(columns)) != len(columns)):
            error(name, f'{name} needs exactly {FACTOR_COUNTS[name]} unique explicit factor columns')
        elif not set(columns).issubset(factors.columns):
            error(name, 'factor definition references missing columns')
    if result['errors']:
        return result
    result['metadata']['factor_definitions'] = {name: list(columns) for name, columns in definitions.items()}
    for model, portfolio in portfolios.items():
        try:
            if not isinstance(model, str) or not model.strip() or '.' in model:
                raise ValueError('portfolio model must be a nonempty name without periods')
            if (not isinstance(portfolio, pd.DataFrame) or portfolio.columns.has_duplicates
                    or 'low_minus_high' not in portfolio):
                raise ValueError('portfolio requires a unique low_minus_high column')
            empirical._monthly_index(portfolio.index)
            if portfolio.index.name in {'formation_date', 'formation_month'}:
                raise ValueError('portfolio dates must label holding months, not formation months')
            empirical._finite(portfolio['low_minus_high'], 'low_minus_high')
        except ValueError as exc:
            error(str(model), exc)
            continue
        periods = portfolio.index.to_period('M')
        for period, mask in (('full', np.ones(len(portfolio), dtype=bool)),
                             ('pre2018', periods < pd.Period('2018-01', freq='M')),
                             ('post2018', periods >= pd.Period('2018-01', freq='M'))):
            selected = portfolio.loc[mask, 'low_minus_high']
            for name in FACTOR_COUNTS:
                key = f'table3.{period}.{model}.{name}'
                if name not in definitions:
                    result['statistics'][key] = {'status': 'NOT_RUN', 'reason': 'factor model not supplied'}
                    continue
                try:
                    if selected.empty:
                        result['statistics'][key] = {'status': 'NOT_RUN', 'reason': 'no holding months in period'}
                        continue
                    if not selected.index.isin(factors.index).all():
                        raise ValueError('factor dates must align exactly with every selected holding month')
                    aligned = factors.loc[selected.index, definitions[name]]
                    stats = empirical.factor_alpha(selected, aligned, maxlags=3)
                    stats.update(status='ESTIMATED', start_date=str(selected.index.min().date()),
                                 end_date=str(selected.index.max().date()), factors=list(definitions[name]))
                    result['statistics'][key] = _json_safe(stats)
                    if math.isfinite(stats['alpha']):
                        result['observed'][key] = float(stats['alpha'])
                        result['observed'][key + '.t'] = _json_safe(stats['t_stat'])
                except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
                    error(key, exc)
                    result['statistics'][key] = {'status': 'FAILED', 'reason': str(exc)}
    return result
