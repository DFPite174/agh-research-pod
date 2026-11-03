"""Strict monthly research statistics; callers supply point-in-time aligned data.

Returns are decimal simple returns. No routine invents observations, fills a
termination return, shifts prices, or establishes that an input was known at
formation. See docs/empirical-methods.md for the explicitly chosen conventions.
"""
from collections.abc import Mapping, Sequence
from numbers import Integral

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS


def _finite(values, name):
    try:
        result = np.asarray(values, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"{name} contains missing or nonfinite values")
    return result


def mispricing(market, model):
    """Compute (market - model) / model, requiring finite positive prices."""
    market = _finite(market, "market_price")
    model = _finite(model, "model_price")
    if np.any(market <= 0) or np.any(model <= 0):
        raise ValueError("market_price and model_price must be positive")
    try:
        result = (market - model) / model
    except ValueError as exc:
        raise ValueError("market and model shapes do not align") from exc
    if not np.isfinite(result).all():
        raise ValueError("mispricing overflows for supplied prices")
    return float(result) if result.ndim == 0 else result


def _dates(values, name="date"):
    try:
        result = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must contain valid dates") from exc
    if result.hasnans or result.tz is not None:
        raise ValueError(f"{name} must be complete timezone-naive dates")
    if not (result == result.normalize()).all():
        raise ValueError(f"{name} must be dates without intraday timestamps")
    return result


def _monthly_index(index):
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("monthly observations require a DatetimeIndex")
    dates = _dates(index)
    periods = dates.to_period("M")
    if dates.empty or periods.has_duplicates or not periods.is_monotonic_increasing:
        raise ValueError("dates must be nonempty, unique monthly observations in increasing order")
    if len(dates) > 1 and not (np.diff(periods.asi8) == 1).all():
        raise ValueError("missing calendar months require explicit sample handling; no silent gaps")
    return dates


_PORTFOLIO_COLUMNS = ["date", *[f"q{i}_{kind}" for i in range(1, 6) for kind in ("return", "excess")],
                      "low_minus_high", "market_excess", "n_input", "n_bonds", "n_trimmed", "tie_count"]


def form_portfolios(panel, weighting="equal", min_bonds=10, trim=.05):
    """Form five deterministic groups using only each row's formation inputs.

    ``next_return`` and ``risk_free`` must already refer to the NEXT holding
    month. Excluded small months and membership are retained in DataFrame.attrs.
    ``market_excess`` is EW over the complete valid month before price trimming.
    """
    if weighting not in ("equal", "value"):
        raise ValueError("weighting must be 'equal' or 'value'")
    if isinstance(min_bonds, bool) or not isinstance(min_bonds, Integral) or min_bonds < 5:
        raise ValueError("min_bonds must be an integer at least 5")
    if not np.isscalar(trim) or not np.isfinite(trim) or not 0 <= trim < .5:
        raise ValueError("trim must be finite and between 0 inclusive and .5 exclusive")
    required = {"date", "bond_id", "market_price", "model_price", "next_return", "risk_free"}
    if weighting == "value":
        required.add("weight")
    if not isinstance(panel, pd.DataFrame) or not required.issubset(panel.columns):
        raise ValueError(f"panel requires columns {sorted(required)}")
    data = panel.copy()
    data["date"] = _dates(data["date"])
    if data["bond_id"].isna().any() or not data["bond_id"].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
        raise ValueError("bond_id must be a nonempty string")
    if data.duplicated(["date", "bond_id"]).any():
        raise ValueError("duplicate date/bond_id observations")
    if data.groupby(data.date.dt.to_period("M"))["date"].nunique().gt(1).any():
        raise ValueError("each calendar month must have one formation date")
    for name in required - {"date", "bond_id"}:
        data[name] = _finite(data[name], name)
    data["mispricing"] = mispricing(data.market_price, data.model_price)
    if (data.next_return < -1).any() or (data.risk_free <= -1).any():
        raise ValueError("simple returns must be >= -1 and risk_free > -1")
    if weighting == "value" and (data.weight <= 0).any():
        raise ValueError("weight must be strictly positive")
    results, excluded, membership = [], [], []
    for date, month in data.groupby("date", sort=True):
        if month.risk_free.nunique() != 1:
            raise ValueError(f"risk_free must be identical within month {date.date()}")
        n_input = len(month)
        if n_input < min_bonds:
            excluded.append({"date": str(date.date()), "n_input": n_input, "reason": "fewer_than_min_bonds"})
            continue
        # Floor removes exactly k observations per tail; tied prices use IDs.
        k = int(np.floor(n_input * trim))
        accepted = month.sort_values(["market_price", "bond_id"], kind="stable").iloc[k:n_input-k]
        if len(accepted) < 5:
            raise ValueError(f"fewer than five bonds after price trimming for {date.date()}")
        accepted = accepted.sort_values(["mispricing", "bond_id"], kind="stable")
        row = {"date": date, "n_input": n_input, "n_bonds": len(accepted), "n_trimmed": 2*k,
               "tie_count": int(accepted.mispricing.duplicated(keep=False).sum()),
               "market_excess": float(month.next_return.mean() - month.risk_free.iloc[0])}
        for group, positions in enumerate(np.array_split(np.arange(len(accepted)), 5), 1):
            holdings = accepted.iloc[positions]
            returns = holdings.next_return.to_numpy()
            weights = holdings.weight.to_numpy() if weighting == "value" else None
            value = float(np.average(returns, weights=weights))
            row[f"q{group}_return"] = value
            row[f"q{group}_excess"] = value - float(month.risk_free.iloc[0])
            membership.extend({"date": str(date.date()), "bond_id": bond_id, "group": group}
                              for bond_id in holdings.bond_id)
        row["low_minus_high"] = row["q1_return"] - row["q5_return"]
        results.append(row)
    result = pd.DataFrame(results, columns=_PORTFOLIO_COLUMNS)
    result.attrs.update(excluded_months=excluded, membership=membership,
                        tie_policy="ascending mispricing then lexicographic bond_id",
                        trim_policy="floor(n*trim) per market-price tail; price then bond_id",
                        return_timing="date is formation month; next_return and risk_free supplied for next month",
                        market_universe="equal-weight complete valid month before price trimming")
    return result


def _fit(y, x, maxlags, confidence):
    if isinstance(maxlags, bool) or not isinstance(maxlags, Integral) or maxlags < 0:
        raise ValueError("maxlags must be a nonnegative integer")
    if not np.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if len(y) <= max(maxlags, x.shape[1]):
        raise ValueError("insufficient monthly observations for lag and regression dimension")
    if np.linalg.matrix_rank(x) < x.shape[1]:
        raise ValueError("regression design is rank deficient")
    return OLS(y, x, missing="raise").fit(cov_type="HAC", cov_kwds={"maxlags": maxlags, "use_correction": True}, use_t=True)


def _coefficient(fit, index, maxlags, confidence):
    with np.errstate(divide="ignore", invalid="ignore"):
        interval = fit.conf_int(alpha=1-confidence)[index]
        t_stat, p_value = float(fit.tvalues[index]), float(fit.pvalues[index])
    valid_inference = np.isfinite([t_stat, p_value]).all() and fit.bse[index] > 0
    return {"estimate": float(fit.params[index]), "standard_error": float(fit.bse[index]),
            "t_stat": t_stat if valid_inference else None, "p_value": p_value if valid_inference else None,
            "inference_status": "ESTIMATED" if valid_inference else "DEGENERATE",
            "confidence_interval": [float(x) for x in interval], "confidence": confidence,
            "nobs": int(fit.nobs), "maxlags": int(maxlags),
            "covariance": "Newey-West Bartlett HAC; finite-sample n/(n-k) correction; Student-t"}


def hac_mean(values, maxlags=3, confidence=.95):
    """Monthly mean with NW standard error; requires a complete dated Series."""
    if not isinstance(values, pd.Series):
        raise ValueError("values must be a dated pandas Series")
    _monthly_index(values.index)
    y = _finite(values, "values")
    return _coefficient(_fit(y, np.ones((len(y), 1)), maxlags, confidence), 0, maxlags, confidence)


def factor_alpha(returns, factors, maxlags=3, confidence=.95):
    """OLS intercept with NW errors; caller supplies correctly defined excess/L-S.

    No RF subtraction occurs here. All factor dates must match exactly, including
    their labels. Missing dates, values, duplicate factors and singularity fail.
    """
    if not isinstance(returns, pd.Series) or not isinstance(factors, pd.DataFrame):
        raise ValueError("returns must be Series and factors must be DataFrame")
    _monthly_index(returns.index)
    if not returns.index.equals(factors.index):
        raise ValueError("returns and factors dates must align exactly")
    if factors.shape[1] == 0 or factors.columns.has_duplicates or "const" in factors.columns:
        raise ValueError("factors must have unique nonempty columns without reserved 'const'")
    y, f = _finite(returns, "returns"), _finite(factors, "factors")
    fit = _fit(y, np.column_stack((np.ones(len(y)), f)), maxlags, confidence)
    result = _coefficient(fit, 0, maxlags, confidence)
    result.update(alpha=result["estimate"], betas={str(name): float(fit.params[i+1]) for i, name in enumerate(factors.columns)},
                  r_squared=float(fit.rsquared), return_convention="caller-supplied excess or zero-investment return; no RF subtraction")
    return result


def fama_macbeth(panel, dependent, regressors: Sequence[str], date_col="date", maxlags=3, confidence=.95):
    """Separate monthly cross-sectional OLS, then NW inference on mean slopes.

    An intercept is included. Input must have unique date/bond_id observations;
    regressors must already be dated and known at formation by the caller.
    """
    regressors = list(regressors)
    required = [date_col, "bond_id", dependent, *regressors]
    if not regressors or len(set(regressors)) != len(regressors) or "const" in regressors or dependent in regressors:
        raise ValueError("regressors must be unique and exclude dependent and reserved 'const'")
    if not isinstance(panel, pd.DataFrame) or not set(required).issubset(panel.columns):
        raise ValueError(f"panel requires {required}")
    data = panel[required].copy()
    data[date_col] = _dates(data[date_col])
    if data.bond_id.isna().any() or data.duplicated([date_col, "bond_id"]).any():
        raise ValueError("missing bond_id or duplicate monthly bond observation")
    for name in [dependent, *regressors]:
        data[name] = _finite(data[name], name)
    dates = pd.DatetimeIndex(sorted(data[date_col].unique()))
    _monthly_index(dates)
    monthly = []
    for date, cross_section in data.groupby(date_col, sort=True):
        x = np.column_stack((np.ones(len(cross_section)), cross_section[regressors].to_numpy()))
        if len(cross_section) <= x.shape[1]:
            raise ValueError(f"insufficient cross-sectional observations for {date.date()}")
        if np.linalg.matrix_rank(x) < x.shape[1]:
            raise ValueError(f"cross-sectional design rank deficient for {date.date()}")
        coefficients = np.linalg.lstsq(x, cross_section[dependent].to_numpy(), rcond=None)[0]
        monthly.append(dict(date=date, nobs=len(cross_section), **dict(zip(["const", *regressors], coefficients))))
    monthly_frame = pd.DataFrame(monthly).set_index("date")
    summaries = {name: hac_mean(monthly_frame[name], maxlags, confidence) for name in ["const", *regressors]}
    return {"coefficients": summaries, "monthly_coefficients": monthly_frame, "n_months": len(monthly_frame),
            "method": "monthly cross-sectional OLS with intercept; HAC inference on mean coefficients"}


def compare_targets(targets: Mapping, observed: Mapping | None = None, *, atol=1e-8, rtol=0.0):
    """Compare measured values with paper targets; missing measurements stay empty.

    Mapping values are numbers or dicts with ``value``; target dicts may specify
    ``atol``/``rtol``. Observed dicts may retain ``status=BLOCKED/NOT_RUN`` and a
    reason. Passing tolerances is arithmetic agreement, not reproduction proof.
    """
    if not isinstance(targets, Mapping) or (observed is not None and not isinstance(observed, Mapping)):
        raise ValueError("targets and observed must be mappings")
    observed = {} if observed is None else observed
    rows = []
    for name, target in targets.items():
        details = target if isinstance(target, Mapping) else {"value": target}
        expected = float(_finite(details.get("value"), f"target {name}"))
        abs_tol, rel_tol = details.get("atol", atol), details.get("rtol", rtol)
        if not np.isfinite([abs_tol, rel_tol]).all() or abs_tol < 0 or rel_tol < 0:
            raise ValueError("tolerances must be finite and nonnegative")
        measurement = observed.get(name)
        measured = measurement if isinstance(measurement, Mapping) else {"value": measurement}
        value = measured.get("value")
        status, reason = measured.get("status"), measured.get("reason", "")
        if status in ("BLOCKED", "NOT_RUN"):
            value = None
        elif value is None or (np.isscalar(value) and pd.isna(value)):
            status, value = "NOT_RUN", None
            reason = reason or "measurement unavailable"
        else:
            value = float(_finite(value, f"observation {name}"))
            status = "PASS" if np.isclose(value, expected, atol=abs_tol, rtol=rel_tol) else "FAIL"
        rows.append({"target": name, "expected": expected, "observed": value,
                     "error": None if value is None else value-expected,
                     "atol": abs_tol, "rtol": rel_tol, "status": status, "reason": reason})
    return pd.DataFrame(rows, columns=["target", "expected", "observed", "error", "atol", "rtol", "status", "reason"])


def table1_statistics(values):
    """Column descriptive statistics in input units, with no missing-value drops."""
    if not isinstance(values, pd.DataFrame) or values.empty or values.columns.has_duplicates:
        raise ValueError("values must be a nonempty DataFrame with unique model columns")
    result = []
    for name in values.columns:
        array = _finite(values[name], str(name))
        if len(array) < 2:
            raise ValueError("at least two observations required for sample standard deviation")
        result.append({"model": name, "nobs": len(array), "mean": float(array.mean()),
                       "std": float(array.std(ddof=1)), "min": float(array.min()),
                       "p25": float(np.quantile(array, .25)), "median": float(np.median(array)),
                       "p75": float(np.quantile(array, .75)), "max": float(array.max())})
    return pd.DataFrame(result).set_index("model")
