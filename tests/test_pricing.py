"""Independent valuation identities and deterministic contractual examples."""
from dataclasses import replace
import json
import math

import pytest
from scipy.stats import norm

from agh_pod.pricing import BondContract, Coupon, Trigger, contract_from_dict, price


def bond(**changes):
    return replace(BondContract(spot=10, conversion_price=10, maturity=1,
                               risk_free=.03, credit_spread=0, volatility=.25), **changes)


def test_bs_matches_independent_cash_plus_call_formula():
    # 10 shares, underlying value 100, debt redemption 100.
    d1 = (.03 + .25**2 / 2) / .25
    expected = 100 * math.exp(-.03) + 100 * norm.cdf(d1) - 100 * math.exp(-.03) * norm.cdf(d1 - .25)
    assert price(bond(), 'BS')['price'] == pytest.approx(expected, abs=1e-10)


@pytest.mark.parametrize('model', ['BS', 'TF', 'LYW', 'LW', 'ZL'])
def test_maturity_conversion_and_cash_include_redemption_coupon(model):
    assert price(bond(maturity=0, coupons=(Coupon(0, 6),)), model)['price'] == 106
    assert price(bond(maturity=0, spot=12, coupons=(Coupon(0, 6),)), model)['price'] == 120


@pytest.mark.parametrize('model', ['BS', 'TF', 'LYW', 'LW', 'ZL'])
def test_zero_volatility_with_coupon_has_hand_calculated_value(model):
    c = bond(spot=1, volatility=0, coupons=(Coupon(.5, 2), Coupon(1, 5)))
    expected = 2 * math.exp(-.03 * .5) + 105 * math.exp(-.03)
    assert price(c, model)['price'] == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize('model', ['TF', 'LYW', 'LW'])
def test_no_clause_tree_converges_to_bs(model):
    c = bond(coupons=(Coupon(.5, 2), Coupon(1, 5)))
    coarse = price(c, model, steps=100)['price']
    fine = price(c, model, steps=800)['price']
    expected = price(c, 'BS')['price']
    assert abs(fine - expected) < .025
    assert abs(fine - expected) < abs(coarse - expected)


def test_debt_credit_spread_only_discounts_cash_component():
    c = bond(spot=.01, volatility=0, credit_spread=.02,
             coupons=(Coupon(.5, 2), Coupon(1, 5)))
    expected = 2 * math.exp(-.05 * .5) + 105 * math.exp(-.05)
    assert price(c, 'TF')['price'] == pytest.approx(expected, abs=1e-9)
    assert price(c, 'BS')['price'] > expected
    assert price(c, 'ZL')['price'] == pytest.approx(price(c, 'BS')['price'])


def test_tf_cash_equity_split_matches_independent_terminal_integrals():
    c = bond(credit_spread=.02, dividend_yield=.01)
    d1 = (.03-.01+.25**2/2)/.25
    d2 = d1-.25
    expected = 100*math.exp(-.01)*norm.cdf(d1) + 100*math.exp(-.05)*norm.cdf(-d2)
    assert price(c, 'TF', steps=1600)['price'] == pytest.approx(expected, abs=.025)


def test_non_grid_coupon_pv_is_exact_without_clause_events():
    c = bond(spot=.01, volatility=0, coupons=(Coupon(.173, 2), Coupon(1, 5)))
    expected = 2*math.exp(-.03*.173)+105*math.exp(-.03)
    for model in ('TF', 'ZL'):
        assert price(c, model, steps=30, paths=20)['price'] == pytest.approx(expected, abs=1e-9)


def test_no_voluntary_early_conversion_even_with_large_dividend_yield():
    c = bond(spot=20, volatility=0, dividend_yield=2)
    expected = 100*math.exp(-.03)
    for model in ('BS', 'TF', 'LYW', 'LW', 'ZL'):
        assert price(c, model, paths=20)['price'] == pytest.approx(expected, abs=1e-8)


def test_mc_is_reproducible_and_confidence_interval_covers_analytic_value():
    c = bond()
    result = price(c, 'ZL', paths=40000, seed=21)
    assert result == price(c, 'ZL', paths=40000, seed=21)
    assert abs(result['price'] - price(c, 'BS')['price']) < 4 * result['standard_error']
    assert result['standard_error'] > 0
    json.dumps(result, allow_nan=False)


def test_tf_call_is_unconditional_but_zl_uses_rolling_stock_trigger():
    c = bond(spot=5, volatility=0, risk_free=0, call=Trigger(1.3, payment=90))
    assert price(c, 'TF')['price'] == pytest.approx(90)
    assert price(c, 'ZL', paths=20)['price'] == pytest.approx(100)


def test_lyw_and_lw_apply_distinct_paper_proxy_caps():
    c = bond(spot=30, volatility=0, risk_free=0,
             call=Trigger(1.3, payment=101))
    assert price(c, 'LYW')['price'] == pytest.approx(130)
    assert price(c, 'LW')['price'] == pytest.approx(130 * 1.079)


def test_zl_historical_window_triggers_immediate_call_and_call_has_priority():
    c = bond(spot=15, volatility=0, history=(15,) * 14,
             call=Trigger(1.3), put=Trigger(2, payment=180), reset_floor=5)
    result = price(c, 'ZL', paths=20)
    assert result['price'] == 150
    assert result['diagnostics']['call_fraction'] == 1
    assert result['diagnostics']['put_fraction'] == 0


def test_rolling_window_expires_old_qualifying_history():
    c = bond(spot=5, volatility=0, history=(20, 20, 5),
             call=Trigger(1.3, window=3, required=2, start=1/252))
    assert price(c, 'ZL', paths=20)['diagnostics']['call_fraction'] == 0


def test_clause_start_and_end_exclude_inactive_history_trigger():
    c = bond(spot=15, volatility=0, history=(15,)*29,
             call=Trigger(1.3, start=2, end=3))
    assert price(c, 'ZL', paths=20)['diagnostics']['call_fraction'] == 0
    assert price(c, 'TF')['price'] == pytest.approx(150)


def test_zl_put_resets_conversion_price_by_bs_inversion_when_feasible():
    c = bond(spot=5, volatility=0, risk_free=0, history=(5,) * 14,
             put=Trigger(.7, payment=110), reset_floor=1)
    result = price(c, 'ZL', paths=20)
    assert result['price'] == pytest.approx(110, abs=1e-7)
    assert result['diagnostics']['reset_fraction'] == 1
    assert result['diagnostics']['put_fraction'] == 0


def test_zl_infeasible_reset_pays_put_and_excludes_future_coupons():
    c = bond(spot=5, volatility=0, risk_free=0, history=(5,) * 14,
             put=Trigger(.7, payment=110), reset_floor=9,
             coupons=(Coupon(.5, 2), Coupon(1, 5)))
    result = price(c, 'ZL', paths=20)
    assert result['price'] == 110
    assert result['diagnostics']['put_fraction'] == 1


def test_zl_needs_no_reset_floor_when_current_bs_value_already_avoids_put():
    c = bond(spot=5, volatility=0, risk_free=0, history=(5,) * 29,
             put=Trigger(.7, payment=100),
             coupons=(Coupon(.5, 2), Coupon(1, 5)))
    result = price(c, 'ZL', paths=20)
    assert result['price'] == pytest.approx(107)
    assert result['diagnostics']['put_fraction'] == 0
    assert result['diagnostics']['reset_fraction'] == 0


def test_tf_cash_put_is_credit_discounted_even_when_current_conversion_is_larger():
    # The only permitted payoff at .5 is cash put; European conversion is later.
    from math import exp
    c = bond(spot=40, volatility=0, risk_free=0, credit_spread=.1, dividend_yield=2,
             put=Trigger(.7, start=.5, end=.5, payment=110))
    assert price(c, 'TF', steps=200)['price'] == pytest.approx(110 * exp(-.1*.5), abs=1e-8)


def test_parser_constructs_nested_terms_and_reports_approximations():
    c = contract_from_dict(dict(spot=10, conversion_price=10, maturity=1,
        risk_free=.03, credit_spread=.01, volatility=.2,
        coupons=[dict(time=1, amount=5)], call=dict(ratio=1.3)))
    assert c.coupons == (Coupon(1, 5),)
    assert c.call.required == 15
    assert price(c, 'ZL', paths=20)['method_status'] != 'EXACT_REPRODUCTION'


@pytest.mark.parametrize('changes', [dict(spot=0), dict(conversion_price=-1),
    dict(maturity=-1), dict(volatility=-.1), dict(risk_free=float('nan')),
    dict(face=float('inf')), dict(credit_spread=-.1), dict(reset_floor=11),
    dict(coupons=(Coupon(2, 1),)), dict(coupons=(Coupon(.5, -1),)),
    dict(history=(float('nan'),)), dict(call=Trigger(1.3, required=31)),
    dict(put=Trigger(.7, start=2, end=1)), dict(call=Trigger(float('inf')))])
def test_invalid_contracts_are_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        price(bond(**changes), 'BS')


@pytest.mark.parametrize('kwargs', [dict(model='wrong'), dict(model='TF', steps=0),
    dict(model='TF', steps=1.5), dict(model='ZL', paths=1),
    dict(model='ZL', paths=100000000), dict(model='ZL', seed=-1)])
def test_invalid_or_unbounded_computation_is_rejected(kwargs):
    with pytest.raises(ValueError):
        price(bond(), **kwargs)


def test_unknown_json_keys_are_rejected():
    with pytest.raises((ValueError, TypeError)):
        contract_from_dict({'spot': 10, 'conversion_price': 10, 'maturity': 1,
                            'risk_free': .03, 'credit_spread': 0, 'volatility': .2,
                            'reset_flor': 5})


@pytest.mark.filterwarnings('error')
def test_extreme_finite_inputs_reject_nonrepresentable_cashflows():
    with pytest.raises(ValueError):
        price(bond(face=1e308, spot=1e308), 'TF')
