"""Trusted ordinary-equity strategy adapter; candidate expressions are never Python exec."""
from datetime import date, datetime
from decimal import Decimal


def perform_equity(request):
    from contracts import Instrument, CorporateAction
    from engine import BacktestBar, OrderIntent, run_backtest
    from agh_pod.strategy_rules import evaluate_rule, validate_rule

    strategy = request['strategy']
    for name in ('buy', 'sell'):
        validate_rule(strategy[name])
    shares = request['shares']
    if type(shares) is not int or not 100 <= shares <= 100000 or shares % 100:
        raise ValueError('fixed equity shares must be a multiple of 100 within budget')
    instruments = [Instrument(**item) for item in request['instruments']]
    bars = [BacktestBar(symbol=b['symbol'], start=datetime.fromisoformat(b['start']),
                        end=datetime.fromisoformat(b['end']), volume=b['volume'],
                        **{k: Decimal(str(b[k])) for k in ('open', 'high', 'low', 'close')}) for b in request['bars']]
    rules = {(r['symbol'], date.fromisoformat(r['date'])): r['rule'] for r in request['rules']}
    days = [date.fromisoformat(d) for d in request['trading_days']]
    actions = [CorporateAction(**a) for a in request.get('corporate_actions', [])]

    def signal(bar, state):
        if request.get('signal_start') and bar.end.date().isoformat() < request['signal_start']:
            return []
        history = [{k: float(getattr(b, k)) for k in ('open', 'high', 'low', 'close', 'volume')}
                   for b in state.history[bar.symbol][-253:]]
        position = int(state.positions.get(bar.symbol, 0))
        sellable = int(state.sellable.get(bar.symbol, 0))
        if position and sellable and evaluate_rule(strategy['sell'], history):
            return [OrderIntent(bar.symbol, 'SELL', sellable)]
        if not position and evaluate_rule(strategy['buy'], history):
            return [OrderIntent(bar.symbol, 'BUY', shares)]
        return []

    result = run_backtest(instruments, bars, rules, signal, trading_days=days,
                          corporate_actions=actions, initial_cash=Decimal(str(request['initial_cash'])),
                          participation_rate=request['participation_rate'])
    return {'status': 'EXECUTED_NOT_QUALIFIED', 'result': result.to_dict(),
            'signal_timing': 'closed raw bar only; earliest execution at next bar open',
            'strategy_language': 'bounded historical expressions; no eval/exec',
            'paper_reproduction_certified': False}
