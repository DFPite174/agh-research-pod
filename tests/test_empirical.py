"""Synthetic arithmetic and validation checks; these are not empirical findings."""
import importlib

import numpy as np
import pandas as pd
import pytest
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant


def empirical():
    # A real missing module is an assertion failure in the initial red cycle.
    assert importlib.util.find_spec("agh_pod.empirical") is not None, "empirical implementation missing"
    return importlib.import_module("agh_pod.empirical")


def panel(n=20, dates=("2020-01-31",)):
    return pd.DataFrame([
        dict(date=date, bond_id=f"B{i:02d}", market_price=100 + i,
             model_price=100, next_return=i / 100, risk_free=.002)
        for date in dates for i in range(n)
    ])


def series(values):
    return pd.Series(values, index=pd.date_range("2020-01-31", periods=len(values), freq="ME"))


def test_mispricing_uses_model_denominator():
    result = empirical().mispricing([110, 90], [100, 120])
    np.testing.assert_allclose(result, [.1, -.25])


@pytest.mark.parametrize("market,model", [(100, 0), (np.nan, 100), (100, np.inf), (-1, 100)])
def test_mispricing_rejects_invalid_prices(market, model):
    with pytest.raises(ValueError):
        empirical().mispricing(market, model)


def test_portfolios_rank_trim_and_do_not_double_subtract_rf():
    result = empirical().form_portfolios(panel()).iloc[0]
    # One price rank removed at either end; 18 divide into 4,4,4,3,3 bonds.
    assert result.q1_return == pytest.approx(.025)
    assert result.q5_return == pytest.approx(.17)
    assert result.q1_excess == pytest.approx(.023)
    assert result.low_minus_high == pytest.approx(-.145)
    assert result.market_excess == pytest.approx(.093)
    assert (result.n_input, result.n_bonds, result.n_trimmed) == (20, 18, 2)


def test_portfolios_ties_broken_by_bond_identifier_and_never_future_prices():
    data = panel(n=10, dates=("2020-01-31", "2020-02-29"))
    data["market_price"] = 100
    data.loc[data.date == "2020-02-29", "market_price"] = 500
    result = empirical().form_portfolios(data.sample(frac=1, random_state=4), trim=0)
    assert result.iloc[0].q1_return == pytest.approx(.005)
    assert result.iloc[0].tie_count == 10
    assert result.iloc[0].low_minus_high == pytest.approx(-.08)
    assert list(result.date) == [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")]


def test_missing_aligned_next_return_is_not_computed_from_future_prices():
    with pytest.raises(ValueError, match="next_return"):
        empirical().form_portfolios(panel().drop(columns="next_return"))
    data = panel()
    data.loc[19, "next_return"] = np.nan  # missing termination must fail even if trimmed
    with pytest.raises(ValueError, match="next_return"):
        empirical().form_portfolios(data)


@pytest.mark.parametrize("change", ["duplicate", "rf", "price", "id", "nonfinite"])
def test_portfolios_reject_invalid_panel_without_silent_drops(change):
    data = panel()
    if change == "duplicate":
        data = pd.concat([data, data.iloc[[0]]])
    elif change == "rf":
        data.loc[0, "risk_free"] = .01
    elif change == "price":
        data.loc[0, "model_price"] = 0
    elif change == "id":
        data.loc[0, "bond_id"] = None
    else:
        data.loc[0, "next_return"] = np.inf
    with pytest.raises(ValueError):
        empirical().form_portfolios(data)


def test_small_month_exclusion_is_recorded_and_not_hidden():
    data = pd.concat([panel(n=9), panel(n=10, dates=("2020-02-29",))])
    result = empirical().form_portfolios(data, trim=0)
    assert len(result) == 1
    assert result.attrs["excluded_months"] == [{"date": "2020-01-31", "n_input": 9, "reason": "fewer_than_min_bonds"}]
    assert empirical().form_portfolios(panel(n=9)).empty


def test_value_weighting_uses_explicit_positive_weights():
    data = panel(n=10)
    with pytest.raises(ValueError, match="weight"):
        empirical().form_portfolios(data, weighting="value", trim=0)
    data["weight"] = 1
    data.loc[1, "weight"] = 3
    result = empirical().form_portfolios(data, weighting="value", trim=0).iloc[0]
    assert result.q1_return == pytest.approx(.0075)
    assert result.market_excess == pytest.approx(.043)  # market remains equal-weight
    data.loc[1, "weight"] = 0
    with pytest.raises(ValueError, match="weight"):
        empirical().form_portfolios(data, weighting="value", trim=0)


@pytest.mark.parametrize("kwargs", [{"trim": .49}, {"trim": -.01}, {"min_bonds": 4}, {"weighting": "other"}])
def test_portfolio_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        empirical().form_portfolios(panel(n=10), **kwargs)


def test_hac_mean_matches_independent_statsmodels_constant_regression():
    y = series([.02, .03, -.01, .04, -.02, .01, .015, .005, -.005, .035])
    reference = OLS(y.to_numpy(), np.ones((len(y), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}, use_t=True)
    result = empirical().hac_mean(y)
    assert result["estimate"] == pytest.approx(reference.params[0])
    assert result["standard_error"] == pytest.approx(reference.bse[0])
    assert result["t_stat"] == pytest.approx(reference.tvalues[0])
    assert result["p_value"] == pytest.approx(reference.pvalues[0])
    assert result["nobs"] == 10


def test_hac_rejects_missing_duplicate_unordered_or_undated_months():
    good = series([.01, .02, .04, .03, -.01])
    invalid = [good.drop(good.index[2]), good.iloc[::-1], pd.Series(good.to_numpy()),
               pd.concat([good, good.iloc[[-1]]])]
    bad = good.copy()
    bad.iloc[0] = np.nan
    invalid.append(bad)
    for y in invalid:
        with pytest.raises(ValueError):
            empirical().hac_mean(y)


def test_zero_variance_hac_keeps_undefined_inference_explicit_and_json_safe():
    import json
    result = empirical().hac_mean(series([0., 0., 0., 0., 0.]))
    assert result["estimate"] == 0
    assert result["standard_error"] == 0
    assert result["t_stat"] is None
    assert result["p_value"] is None
    assert result["inference_status"] == "DEGENERATE"
    json.dumps(result, allow_nan=False)


def test_insufficient_months_do_not_report_hac_significance():
    with pytest.raises(ValueError, match="insufficient"):
        empirical().hac_mean(series([.01, .02, .03]))


def test_factor_alpha_matches_ols_hac_and_requires_exact_dates():
    y = series([.01, .03, .005, -.01, .04, .025, -.005, .02, .015, .035])
    factors = pd.DataFrame({"MKT": [.02, .01, -.03, -.02, .03, .015, -.01, .025, .005, .04]}, index=y.index)
    reference = OLS(y.to_numpy(), add_constant(factors.to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}, use_t=True)
    result = empirical().factor_alpha(y, factors)
    assert result["alpha"] == pytest.approx(reference.params[0])
    assert result["standard_error"] == pytest.approx(reference.bse[0])
    assert result["betas"]["MKT"] == pytest.approx(reference.params[1])
    with pytest.raises(ValueError, match="align"):
        empirical().factor_alpha(y, factors.iloc[:-1])
    factors.iloc[0, 0] = np.nan
    with pytest.raises(ValueError):
        empirical().factor_alpha(y, factors)


def test_fama_macbeth_cross_sections_then_hac_average_slopes():
    data = pd.DataFrame([dict(date=date, bond_id=f"B{i}", x=i, y=.5 + slope * i)
                         for date, slope in zip(series(range(8)).index, [1, 2, 1, 3, 2, 4, 3, 2])
                         for i in range(5)])
    result = empirical().fama_macbeth(data, "y", ["x"])
    assert result["coefficients"]["x"]["estimate"] == pytest.approx(2.25)
    assert len(result["monthly_coefficients"]) == 8
    reference = empirical().hac_mean(series([1, 2, 1, 3, 2, 4, 3, 2]))
    assert result["coefficients"]["x"]["standard_error"] == pytest.approx(reference["standard_error"])
    data.loc[0, "y"] = np.nan
    with pytest.raises(ValueError):
        empirical().fama_macbeth(data, "y", ["x"])


def test_rank_deficient_factor_and_cross_section_designs_fail():
    y = series([.01, .02, .03, .04, .05, .06])
    with pytest.raises(ValueError, match="rank"):
        empirical().factor_alpha(y, pd.DataFrame({"MKT": 1}, index=y.index))
    data = panel(n=10, dates=tuple(str(x.date()) for x in y.index))
    with pytest.raises(ValueError, match="rank"):
        empirical().fama_macbeth(data, "next_return", ["risk_free"])


def test_target_comparison_never_fills_missing_observations_with_paper_values():
    result = empirical().compare_targets({"table2": .012, "table3": .015}, {"table2": .01201}, atol=.0001).set_index("target")
    assert result.loc["table2", "status"] == "PASS"
    assert result.loc["table3", "status"] == "NOT_RUN"
    assert pd.isna(result.loc["table3", "observed"])
    blocked = empirical().compare_targets({"x": 1}, {"x": {"status": "BLOCKED", "reason": "licensed data absent"}}).iloc[0]
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "licensed data absent"


def test_descriptive_statistics_keep_units_and_missing_errors():
    result = empirical().table1_statistics(pd.DataFrame({"BS": [.01, .02, .03], "TF": [.02, .03, .04]}))
    assert result.loc["BS", "mean"] == pytest.approx(.02)
    assert result.loc["BS", "nobs"] == 3
    with pytest.raises(ValueError):
        empirical().table1_statistics(pd.DataFrame({"BS": [1, np.nan]}))
