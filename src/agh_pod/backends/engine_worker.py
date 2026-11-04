"""Private subprocess protocol; no arbitrary callable or shell operations."""

from datetime import date, datetime
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def perform(request):
    # Load our own adjacent module without requiring package installation in the engine environment.
    sys.path.insert(0, str(Path(__file__).parent))
    from nautilus import inspect_backend
    info = inspect_backend(request["engine_root"])
    if not info["version_matches"] or not info["tracked_worktree_clean"]:
        return {**info, "status": "BLOCKED_ENGINE_VERSION", "reason": "pinned clean engine checkout required"}
    if request.get("action") not in {"probe", "run", "equity"}:
        raise ValueError("unknown worker action")
    try:
        version = importlib.metadata.version("nautilus_trader")
    except importlib.metadata.PackageNotFoundError:
        return {**info, "status": "BLOCKED_DEPENDENCIES", "reason": "NautilusTrader not installed in engine Python"}
    if version != "1.231.0":
        return {**info, "status": "BLOCKED_DEPENDENCIES", "reason": "NautilusTrader1.231.0 required"}
    info["nautilus_version"] = version
    info["engine_python"] = sys.version
    info["engine_dependencies"] = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "pydantic")}
    sys.path.insert(0, request["engine_root"])
    if request["action"] == "equity":
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from equity_worker import perform_equity
        return {**info, **perform_equity(request)}
    from contracts.models import ConvertibleBondInstrument, Venue
    from engine import BacktestBar, OrderIntent, run_backtest
    if request["action"] == "probe":
        zone = ZoneInfo("Asia/Shanghai")
        instruments = [ConvertibleBondInstrument(symbol="110001.SH", exchange=Venue.SSE)]
        bars = [BacktestBar("110001.SH", datetime(2017, 1, 3, 9, 30, tzinfo=zone),
                            datetime(2017, 1, 3, 15, tzinfo=zone), *(Decimal("100") for _ in range(4)), 1000)]
        rules = {("110001.SH", date(2017, 1, 3)): dict(trade_status="OPEN", limit_state="UNBOUNDED",
                  buy_min=10, buy_step=10, sell_min=10, sell_step=10, max_order=100000)}
        sessions = [date(2017, 1, 3)]
        signal = lambda bar, state: []
    else:
        if request.get("asset_class") != "CONVERTIBLE_BOND":
            raise ValueError("convertible assets must not be disguised as equities")
        instruments = [ConvertibleBondInstrument(**item) for item in request["instruments"]]
        bars = [BacktestBar(symbol=b["symbol"], start=datetime.fromisoformat(b["start"]),
                           end=datetime.fromisoformat(b["end"]), volume=b["volume"],
                           **{k: Decimal(str(b[k])) for k in ("open", "high", "low", "close")}) for b in request["bars"]]
        rules = {(r["symbol"], date.fromisoformat(r["date"])): r["rule"] for r in request["rules"]}
        sessions = [date.fromisoformat(s) for s in request["trading_days"]]
        intents = request.get("intents", [])
        emitted = set()
        def signal(bar, state):
            output = []
            for i, item in enumerate(intents):
                if i not in emitted and item["symbol"] == bar.symbol and datetime.fromisoformat(item["formed_at"]) <= bar.end:
                    output.append(OrderIntent(item["symbol"], item["side"], item["quantity"]))
                    emitted.add(i)
            return output
    try:
        result = run_backtest(instruments, bars, rules, signal, trading_days=sessions,
                              initial_cash=Decimal(str(request.get("initial_cash", "100000"))))
    except ValueError as exc:
        if "cash equities" in str(exc) or "0.01 price tick" in str(exc):
            return {**info, "status": "BLOCKED_ENGINE_CAPABILITY", "convertible_instrument_accepted": False,
                    "reason": str(exc), "paper_reproduction_certified": False}
        return {**info, "status": "FAILED", "reason": "engine rejected input contract", "error_type": type(exc).__name__}
    return {**info, "status": "EXECUTED_NOT_QUALIFIED", "convertible_instrument_accepted": True,
            "result": result.to_dict(), "paper_reproduction_certified": False,
            "reason": "Execution alone does not qualify CB fees,T+0,events or paper short leg."}


if __name__ == "__main__":
    try:
        result = perform(json.loads(sys.stdin.read(25_000_000)))
    except Exception as exc:
        result = {"status": "FAILED", "reason": "engine integration exception", "error_type": type(exc).__name__}
    print("AGH_RESULT=" + json.dumps(result, ensure_ascii=False, allow_nan=False))
