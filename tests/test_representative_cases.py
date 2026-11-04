"""Acceptance helpers: verify source units/annual exclusion and comparison math."""
import importlib.util
from pathlib import Path
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('representative_cases',Path(__file__).parents[1]/'examples/quant/representative_cases.py')
suite=importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


def test_french_monthly_only_and_percent_conversion():
    months=pd.date_range('1960-01-31','2024-12-31',freq='ME')
    raw=('header\n'+ '\n'.join(d.strftime('%Y%m')+',1,2,3,0.1' for d in months)+'\n2024,99,99,99,99').encode()
    data=suite.french_data(raw)
    assert len(data)==769
    assert data.market.iloc[0]==0.01
    assert data.market_12m.iloc[0]==pytest.approx(0.12)
    assert data.date.iloc[0]==pd.Timestamp('1960-12-31')
    with pytest.raises(ValueError,match='complete'): suite.french_data(b'196001,1,2,3,4')


def test_stronger_baseline_not_selected_to_make_model_look_good():
    records=[{'actual':1.,'forecast':0.5,'baseline':0.,'persistence':0.9}]*12
    result=suite.improvement(records)
    assert result['vs_mean']==pytest.approx(.75)
    assert result['vs_stronger']==pytest.approx(-24.)
