"""Synthetic identification and calendar checks; no historical-return evidence."""
import importlib
import json

import numpy as np
import pandas as pd
import pytest


def evaluate(*args):
    assert importlib.util.find_spec('agh_pod.factor_evaluation') is not None, 'factor evaluation missing'
    return importlib.import_module('agh_pod.factor_evaluation').evaluate_factor_models(*args)


def inputs():
    rng = np.random.default_rng(174)
    dates = pd.date_range('2014-01-31', periods=96, freq='ME', name='holding_month')
    factors = pd.DataFrame(rng.normal(0, .03, (96, 5)), index=dates, columns=list('ABCDE'))
    y = .008 + factors.to_numpy() @ np.array([.2, -.1, .3, -.2, .15])
    # Make error independent of intercept and factors within each split so the
    # imposed alpha is exact for full/pre/post while standard errors stay real.
    for rows in (slice(0,48), slice(48,96)):
        design = np.column_stack([np.ones(48), factors.iloc[rows].to_numpy()])
        noise = rng.normal(0, .003, 48)
        y[rows] += noise - design @ np.linalg.lstsq(design, noise, rcond=None)[0]
    portfolios = {'BS': pd.DataFrame({'low_minus_high':y}, index=dates)}
    definitions = {'FF5':list('ABCDE')}
    return portfolios, factors, definitions


def test_imposed_observed_alpha_is_estimated_with_nw3_for_holding_month_splits():
    result = evaluate(*inputs())
    for period, nobs in [('full',96),('pre2018',48),('post2018',48)]:
        key = f'table3.{period}.BS.FF5'
        assert result['observed'][key] == pytest.approx(.008,abs=1e-12)
        assert np.isfinite(result['observed'][key+'.t'])
        assert result['statistics'][key]['nobs'] == nobs
        assert result['statistics'][key]['maxlags'] == 3
    assert not result['errors']
    assert result['statistics']['table3.full.BS.Carhart4']['status'] == 'NOT_RUN'
    assert 'table3.full.BS.Carhart4' not in result['observed']
    json.dumps(result, allow_nan=False)


def test_factor_superset_is_sliced_without_interpolating_dates():
    portfolios,factors,definitions=inputs()
    extra = factors.iloc[[-1]].copy()
    extra.index = pd.DatetimeIndex(['2022-01-31'])
    result=evaluate(portfolios,pd.concat([factors,extra]),definitions)
    assert result['observed']['table3.full.BS.FF5'] == pytest.approx(.008)


@pytest.mark.parametrize('change', ['missing_factor_month','shifted_labels','duplicate_factor_month',
                                  'portfolio_gap','not_datetime','missing_value'])
def test_bad_calendars_or_values_are_explicit_errors_with_no_full_sample_claim(change):
    portfolios,factors,definitions=inputs()
    if change=='missing_factor_month':
        factors=factors.drop(factors.index[12])
    elif change=='shifted_labels':
        factors.index=factors.index-pd.Timedelta(days=1)
    elif change=='duplicate_factor_month':
        factors=pd.concat([factors.iloc[:1],factors])
    elif change=='portfolio_gap':
        portfolios['BS']=portfolios['BS'].drop(portfolios['BS'].index[12])
    elif change=='not_datetime':
        portfolios['BS'].index=range(96)
    else:
        factors.iloc[12,0]=np.nan
    result=evaluate(portfolios,factors,definitions)
    assert result['errors']
    assert 'table3.full.BS.FF5' not in result['observed']
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('definitions', [{'Unknown':list('ABCDE')},{'FF5':list('ABCD')},
    {'FF5':list('ABCDD')},{'FF5':list('ABCDZ')},{'FF5':'ABCDE'}])
def test_invalid_definitions_are_not_silently_normalized(definitions):
    portfolios,factors,_=inputs()
    result=evaluate(portfolios,factors,definitions)
    assert result['errors'] and not result['observed']


def test_all_known_factor_model_names_and_counts_are_supported():
    portfolios,factors,_=inputs()
    definitions={'Carhart4':list('ABCD'),'FF5':list('ABCDE'),'HXZ4':list('ABCD'),
                 'SY4':list('ABCD'),'DHS3':list('ABC')}
    result=evaluate(portfolios,factors,definitions)
    assert len(result['observed']) == 30
    assert not result['errors']


def test_rank_deficient_regression_is_explicitly_failed():
    portfolios,factors,definitions=inputs()
    factors['E']=factors['D']
    result=evaluate(portfolios,factors,definitions)
    assert not result['observed'] and result['errors']
    assert result['statistics']['table3.full.BS.FF5']['status']=='FAILED'
