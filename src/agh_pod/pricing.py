"""Convertible-bond pricing methods with explicit reproduction limitations."""
from dataclasses import dataclass
from math import inf, isfinite, ceil, exp, log, sqrt
from numbers import Real, Integral

import numpy as np
from scipy.special import ndtr


@dataclass(frozen=True)
class Coupon:
    time: float
    amount: float


@dataclass(frozen=True)
class Trigger:
    ratio: float
    window: int = 30
    required: int = 15
    start: float = 0
    end: float = inf
    payment: float = 100


@dataclass(frozen=True, kw_only=True)
class BondContract:
    spot: float
    conversion_price: float
    maturity: float
    risk_free: float
    credit_spread: float
    volatility: float
    face: float = 100
    dividend_yield: float = 0
    coupons: tuple[Coupon, ...] = ()
    call: Trigger | None = None
    put: Trigger | None = None
    reset_floor: float | None = None
    history: tuple[float, ...] = ()


def contract_from_dict(data):
    """Parse only documented fields; reject misspellings rather than ignoring them."""
    if not isinstance(data, dict):
        raise TypeError('contract must be an object')
    values = dict(data)
    if 'coupons' in values:
        values['coupons'] = tuple(Coupon(**item) for item in values['coupons'])
    for name in ('call', 'put'):
        if values.get(name) is not None:
            values[name] = Trigger(**values[name])
    if 'history' in values:
        values['history'] = tuple(values['history'])
    contract = BondContract(**values)
    _validate(contract)
    return contract


def _number(value, name, minimum=None, strict=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if minimum is not None and (value < minimum or (strict and value == minimum)):
        raise ValueError(f'{name} must be {">" if strict else ">="} {minimum}')


def _validate(c):
    if not isinstance(c, BondContract):
        raise TypeError('contract must be BondContract')
    for name in ('face', 'spot', 'conversion_price'):
        _number(getattr(c, name), name, 0, True)
    for name in ('maturity', 'volatility', 'credit_spread', 'dividend_yield'):
        _number(getattr(c, name), name, 0)
    _number(c.risk_free, 'risk_free')
    if c.maturity > 100 or c.volatility > 5 or abs(c.risk_free) > 1 or c.credit_spread > 1:
        raise ValueError('contract exceeds numerical domain (T<=100, sigma<=5, |r|<=1, spread<=1)')
    if c.reset_floor is not None:
        _number(c.reset_floor, 'reset_floor', 0, True)
        if c.reset_floor > c.conversion_price:
            raise ValueError('reset_floor cannot exceed initial conversion price')
    if not isinstance(c.coupons, (tuple, list)) or len(c.coupons) > 1000:
        raise ValueError('coupons must be a sequence of at most 1000 Coupon terms')
    previous = -1
    for coupon in c.coupons:
        if not isinstance(coupon, Coupon):
            raise TypeError('coupons must contain Coupon terms')
        _number(coupon.time, 'coupon time', 0)
        _number(coupon.amount, 'coupon amount', 0)
        if coupon.time > c.maturity or coupon.time < previous:
            raise ValueError('coupon times must be ordered and no later than maturity')
        previous = coupon.time
    for name in ('call', 'put'):
        clause = getattr(c, name)
        if clause is None:
            continue
        if not isinstance(clause, Trigger):
            raise TypeError(f'{name} must be Trigger')
        _number(clause.ratio, f'{name} ratio', 0, True)
        _number(clause.payment, f'{name} payment', 0, True)
        _number(clause.start, f'{name} start', 0)
        if clause.end != inf:
            _number(clause.end, f'{name} end', 0)
        if clause.end < clause.start:
            raise ValueError('trigger end precedes start')
        for field in ('window', 'required'):
            value = getattr(clause, field)
            if isinstance(value, bool) or not isinstance(value, Integral) or not 1 <= value <= 10000:
                raise ValueError('trigger window/required must be integers in [1,10000]')
        if clause.required > clause.window:
            raise ValueError('required observations cannot exceed window')
    if not isinstance(c.history, (tuple, list)) or len(c.history) > 10000:
        raise ValueError('history must be at most 10000 historical stock prices')
    for stock in c.history:
        _number(stock, 'historical stock price', 0, True)


def _terminal_cash(c):
    return c.face + sum(x.amount for x in c.coupons if x.time == c.maturity)


def _bs_value(c, stock=None, strike=None, time=0):
    """Risk-free cash plus exchange option; also vectorized for reset inversion."""
    stock = np.asarray(c.spot if stock is None else stock, dtype=float)
    strike = np.asarray(c.conversion_price if strike is None else strike, dtype=float)
    tau = max(0., c.maturity - time)
    cash = _terminal_cash(c)
    underlying = c.face * stock / strike
    if tau == 0:
        return np.maximum(underlying, cash)
    debt = cash * exp(-c.risk_free * tau)
    equity = underlying * exp(-c.dividend_yield * tau)
    if c.volatility == 0:
        value = np.maximum(equity, debt)
    else:
        vol = c.volatility * sqrt(tau)
        d1 = (np.log(underlying / cash) +
              (c.risk_free - c.dividend_yield + .5*c.volatility**2)*tau) / vol
        value = debt + equity * ndtr(d1) - debt * ndtr(d1 - vol)
    return value + sum(x.amount * exp(-c.risk_free * (x.time - time))
                       for x in c.coupons if time < x.time < c.maturity)


def _active(clause, t):
    return clause is not None and clause.start - 1e-12 <= t <= clause.end + 1e-12


def _coupon_grid(c, intervals, rate):
    """Move intervening coupon events forward with compensation for exact PV."""
    cash = np.zeros(intervals + 1)
    if c.maturity == 0:
        return cash
    dt = c.maturity / intervals
    for x in c.coupons:
        if x.time < c.maturity:
            index = min(intervals, ceil(x.time / dt - 1e-12))
            cash[index] += x.amount * exp(rate * (index*dt - x.time))
    return cash


def _tree(c, model, steps):
    dt = c.maturity / steps
    dx = c.volatility * sqrt(3*dt)
    # Fixed probabilities avoid negative weights; drift correction preserves E[S].
    center = (c.risk_free-c.dividend_yield)*dt - np.logaddexp(
        np.log(2/3), np.logaddexp(dx, -dx) - log(6))
    if abs(center)*steps + dx*steps > 650:
        raise ValueError('tree stock range overflows; reduce steps/domain')
    terminal = c.spot * np.exp(center*steps + np.arange(-steps, steps+1)*dx)
    conversion = terminal * c.face/c.conversion_price
    cash = np.where(conversion > _terminal_cash(c), 0., _terminal_cash(c))
    value = np.maximum(conversion, _terminal_cash(c))
    coupons = _coupon_grid(c, steps, c.risk_free+c.credit_spread)
    value += coupons[-1]
    cash += coupons[-1]
    discount_equity = exp(-c.risk_free*dt)
    discount_cash = exp(-(c.risk_free+c.credit_spread)*dt)
    for i in range(steps-1, -1, -1):
        expected_cash = (cash[:-2] + 4*cash[1:-1] + cash[2:])/6
        expected_equity = ((value-cash)[:-2] + 4*(value-cash)[1:-1] + (value-cash)[2:])/6
        cash = discount_cash*expected_cash + coupons[i]
        value = discount_equity*expected_equity + cash
        t = i*dt
        stock = c.spot*np.exp(center*i + np.arange(-i, i+1)*dx)
        conversion = stock*c.face/c.conversion_price
        if _active(c.call, t):
            if model == 'TF':
                payout = np.maximum(c.call.payment, conversion)
                exercise = value > payout
                cash = np.where(exercise, np.where(conversion > c.call.payment, 0., c.call.payment), cash)
                value = np.minimum(value, payout)
            else:
                threshold = c.face*c.call.ratio*(1.079 if model == 'LW' else 1)
                capped = value >= max(threshold, c.call.payment)
                boundary = np.maximum(conversion, cash)
                # Proxy boundary replaces path-dependent exercise with a value cap.
                value = np.where(capped, threshold, boundary)
                cash = np.where(capped, 0., np.where(conversion > cash, 0., cash))
        if _active(c.put, t):
            eligible = np.ones_like(value, dtype=bool) if model == 'TF' else (
                c.put.payment >= np.maximum(c.face*c.put.ratio*(.86 if model == 'LW' else 1), cash))
            floor = c.put.payment if model == 'TF' else np.maximum(conversion, c.put.payment)
            exercise = eligible & (value < floor)
            value = np.where(exercise, floor, value)
            put_cash = c.put.payment if model == 'TF' else np.where(conversion > c.put.payment, 0., c.put.payment)
            cash = np.where(exercise, put_cash, cash)
    return float(value[0]), dict(steps=steps, tree='recombining trinomial, probabilities 1/6,2/3,1/6',
                               coupon_grid_max_delay=c.maturity/steps)


def _mc(c, paths, seed):
    n = max(1, ceil(c.maturity*252))
    dt = c.maturity/n
    rng = np.random.default_rng(seed)
    stock = np.full(paths, c.spot, dtype=float)
    strike = np.full(paths, c.conversion_price, dtype=float)
    alive = np.ones(paths, dtype=bool)
    outcome = np.zeros(paths)
    reset_any = np.zeros(paths, dtype=bool)
    counts = dict(call=0, put=0)
    states = {}
    for name in ('call', 'put'):
        clause = getattr(c, name)
        if clause is not None:
            # Historical qualifications use the initial conversion price.
            ring = np.zeros((clause.window, paths), dtype=bool)
            past = c.history[-(clause.window-1):] if clause.window > 1 else ()
            for j, observation in enumerate(past):
                ring[j] = observation >= clause.ratio*c.conversion_price if name == 'call' else observation <= clause.ratio*c.conversion_price
            states[name] = [ring, ring.sum(axis=0), len(past)]
    coupons = _coupon_grid(c, n, c.risk_free)
    for i in range(n+1):
        t = i*dt
        if i:
            stock *= np.exp((c.risk_free-c.dividend_yield-.5*c.volatility**2)*dt +
                            c.volatility*sqrt(dt)*rng.standard_normal(paths))
        triggered = {}
        for name, (ring, count, position) in states.items():
            clause = getattr(c, name)
            slot = position % clause.window
            count -= ring[slot]
            ring[slot] = stock >= clause.ratio*strike if name == 'call' else stock <= clause.ratio*strike
            count += ring[slot]
            states[name][2] += 1
            triggered[name] = alive & (count >= clause.required) & _active(clause, t)
        # Maturity conversion/redemption supersedes optional clauses on the same day.
        if i == n:
            outcome[alive] += np.maximum(stock[alive]*c.face/strike[alive], _terminal_cash(c))*exp(-c.risk_free*t)
            outcome[alive] += coupons[i]*exp(-c.risk_free*t)
            break
        if 'call' in triggered:
            mask = triggered['call']
            outcome[mask] += np.maximum(stock[mask]*c.face/strike[mask], c.call.payment)*exp(-c.risk_free*t)
            alive[mask] = False
            counts['call'] += int(mask.sum())
        if 'put' in triggered:
            mask = triggered['put'] & alive
            if mask.any():
                indices = np.flatnonzero(mask)
                current = _bs_value(c, stock[indices], strike[indices], t)
                # No legal floor is needed when the issuer need not reset at all.
                mask[indices[current >= c.put.payment]] = False
            if mask.any() and c.reset_floor is not None:
                indices = np.flatnonzero(mask)
                floor_value = _bs_value(c, stock[indices], c.reset_floor, t)
                feasible = floor_value >= c.put.payment
                selected = indices[feasible]
                if len(selected):
                    low = np.full(len(selected), c.reset_floor)
                    high = strike[selected].copy()
                    for _ in range(50):
                        mid = (low+high)/2
                        enough = _bs_value(c, stock[selected], mid, t) >= c.put.payment
                        low = np.where(enough, mid, low)
                        high = np.where(enough, high, mid)
                    strike[selected] = low
                    reset_any[selected] = True
                mask[indices[feasible]] = False
            outcome[mask] += c.put.payment*exp(-c.risk_free*t)
            alive[mask] = False
            counts['put'] += int(mask.sum())
        outcome[alive] += coupons[i]*exp(-c.risk_free*t)
        if not alive.any():
            break
    error = float(outcome.std(ddof=1)/sqrt(paths))
    return float(outcome.mean()), error, dict(paths=paths, seed=int(seed), trading_days=n,
        time_step=dt, call_fraction=counts['call']/paths, put_fraction=counts['put']/paths,
        reset_fraction=float(reset_any.mean()), confidence_95=[float(outcome.mean()-1.96*error), float(outcome.mean()+1.96*error)])


def price(contract, model, steps=200, paths=10000, seed=42):
    """Return a JSON-safe valuation; status never certifies empirical reproduction."""
    c = contract
    _validate(c)
    if not isinstance(model, str) or model.upper() not in ('BS', 'TF', 'LYW', 'LW', 'ZL'):
        raise ValueError('model must be BS, TF, LYW, LW, or ZL')
    model = model.upper()
    for value, name, low, high in ((steps, 'steps', 1, 2000), (paths, 'paths', 2, 200000), (seed, 'seed', 0, 2**63-1)):
        if isinstance(value, bool) or not isinstance(value, Integral) or not low <= value <= high:
            raise ValueError(f'{name} must be an integer in [{low},{high}]')
    n = max(1, ceil(c.maturity*252))
    windows = sum(x.window for x in (c.call, c.put) if x)
    if model == 'ZL' and (n*paths > 50000000 or windows*paths > 20000000):
        raise ValueError('Monte Carlo budget exceeds 50m path days / 20m rolling flags')
    diagnostics = dict(model=model, empirical_reproduction='NOT_VERIFIED',
        voluntary_conversion='maturity only', credit_discount='risk_free' if model in ('BS', 'ZL') else 'cash: risk_free+spread; equity: risk_free',
        assumptions=[])
    if model in ('TF', 'LYW', 'LW'):
        diagnostics['assumptions'].append('Clause boundaries are paper proxies, not rolling stock triggers.')
    if model == 'BS' and (c.call or c.put):
        diagnostics['assumptions'].append('BS ignores call, put and conversion-price reset clauses.')
    if model == 'ZL':
        diagnostics['assumptions'] += ['252 trading days/year; trigger checks include valuation-day spot.',
            'History is oldest-first, excludes spot; past qualifications use the initial conversion price.',
            'Historical qualification flags retain their original conversion-price basis after resets.',
            'Current BS value at least put payment avoids reset/put; otherwise choose highest feasible reset price.',
            'Maturity redemption takes precedence over clauses on maturity day; call precedes put on earlier days.',
            'Coupons on a termination day are excluded unless included in the stated redemption payment.']
        if any(x and len(c.history) < x.window-1 for x in (c.call, c.put)):
            diagnostics['assumptions'].append('Incomplete historical window: missing past observations treated as nonqualifying.')
        if c.put and c.reset_floor is None:
            diagnostics['assumptions'].append('Missing reset floor: triggered paths needing reset settle in cash; no legal floor invented.')
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            if c.maturity == 0:
                value, error = float(max(c.face*c.spot/c.conversion_price, _terminal_cash(c))), 0.
            elif model == 'BS':
                value, error = float(_bs_value(c)), 0.
                value += sum(x.amount for x in c.coupons if x.time == 0)
            elif model == 'ZL':
                value, error, details = _mc(c, paths, seed)
                diagnostics.update(details)
            else:
                value, details = _tree(c, model, steps)
                error = 0.
                diagnostics.update(details)
    except (FloatingPointError, OverflowError) as exc:
        raise ValueError('contract exceeds floating-point valuation domain') from exc
    if not isfinite(value) or not isfinite(error):
        raise ValueError('nonfinite numerical valuation; adjust contract domain')
    diagnostics['standard_error_scope'] = 'Monte Carlo sampling only; excludes discretization and model error' if model == 'ZL' else '0 denotes deterministic computation, not zero numerical/model error'
    return dict(price=value, standard_error=error, diagnostics=diagnostics,
                method_status='ANALYTIC_LIMITED_MODEL' if model == 'BS' else 'IMPLEMENTED_APPROXIMATION')
