# Read-only local lake adapter

The database is supplied explicitly by the caller. There is no committed private database path and no automatic fallback to another database or vendor. DuckDB is a runtime dependency of the project.

```python
from agh_pod.data_lake import audit_lake, read_daily_bars, capability_report, build_paper_dataset

audit = audit_lake(private_database_path)
bars = read_daily_bars(private_database_path, asset="cb", symbols=["113008.SH"],
                       start="2017-01-03", end="20170116")
capabilities = capability_report(private_database_path)
```

`audit_lake` opens an existing database with `read_only=True`, disables external access on the connection, and runs all table queries inside one read transaction. It records the database filename, byte size and SHA256 before/after the audit; a differing fingerprint is reported as `stable=False`. Its returned report excludes the full private database path. A stable fingerprint only establishes that the database bytes observed around this operation matched; it does not establish provider data provenance or historical vintage integrity. Do not run maintenance, synchronization or writers concurrently when producing a frozen audit.

The adapter maps these fixed main-schema base tables:

| Table | Role |
|---|---|
| `tb_cb_basic` | Current bond master and linked stocks |
| `tb_cb_daily` | Raw convertible daily bars |
| `tb_stock_basic` | Stock master |
| `tb_stock_daily` | Raw stock daily bars |
| `tb_trade_cal` | Trading calendar |
| `tb_sync_checkpoint` | Engineering synchronization checkpoints |

The audit reports each mapped table's column names/types and row count. When present, it also reports symbol counts, valid date bounds and distinct dates. Daily quality counts separate duplicate excess rows, missing symbols, invalid dates, nonfinite prices, negative volume, invalid OHLC and the zero-OHLC/zero-volume/positive-close placeholder pattern. A placeholder pattern can be consistent with an upstream nontrading placeholder; it is **not verified suspension evidence**, and the adapter leaves it unchanged.

Month-end coverage is checked against the paper's 2000-07 through 2022-06 calendar. A calendar month is considered known only when all calendar days have a unique valid calendar record. The expected final open day is then compared with observed raw-bar dates. An incomplete calendar does not turn the last downloaded quote into a month-end quote. `monthends_with_rows` and `all_open_dates_present_months` describe aggregate date coverage: even a complete month at this level does not certify that every eligible bond or stock is present.

`read_daily_bars` accepts only `asset="cb"` or `asset="stock"`, six-digit exchange-qualified symbols and valid inclusive dates in `YYYYMMDD` or `YYYY-MM-DD` format. It reads fixed tables with SQL parameters for every filter value. It preserves stored prices, zero bars, volume and amount; it does not infer exchange lots, scale units, fill prices, calculate returns or classify suspension. Missing databases are rejected rather than created.

`capability_report` exposes only the database identity/fingerprint, aggregate summary and paper requirement statuses. The present six-table mapping cannot validate or construct a complete reproduction dataset. `build_paper_dataset` therefore raises a gap summary and writes no CSV or invented observations. It does not backfill `tb_cb_basic.conv_price` into historical dates.

Required additional evidence includes:

- Complete matched 2000-07–2022-06 month-end observations and the paper's sample/exclusion reconciliation.
- At least 250 prior usable stock-return observations at every valuation, with validated corporate-action adjustments.
- Maturity dates, face and redemption terms, full stepped coupons and realized coupon/terminal payments.
- Effective-dated and publication-dated conversion changes, call/put/reset clauses, legal floors, waivers and amendments.
- Historical Chinese treasury **spot** curves for pricing and the separate one-year deposit-rate schedule for excess returns.
- Point-in-time financial observations and the paper-matching five multifactor return libraries.

Synchronization flags and a long trading calendar establish engineering state only. `fully_qualified` remains false and `research_status` remains `not_evaluated`; neither an audit nor raw-bar access constitutes completed pricing, a historical replication, alpha evidence or execution readiness. If the lake later gains more tables, explicit mapping and source qualification must be added before these statuses can change.
