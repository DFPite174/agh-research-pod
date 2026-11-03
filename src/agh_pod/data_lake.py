"""Read-only audit and raw-bar access for the explicitly supplied DuckDB lake.

No routine repairs prices, infers volume units, calls a provider, writes to the
database, or backfills today's conversion price into history. Zero OHLC/volume
with a positive close is reported as a placeholder pattern, not certified
suspension. Calendar coverage is aggregate date coverage, not security-universe
or PIT qualification. The six mapped tables cannot supply a paper-ready dataset.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None


TABLES = ('tb_cb_basic', 'tb_cb_daily', 'tb_stock_basic', 'tb_stock_daily',
          'tb_trade_cal', 'tb_sync_checkpoint')
DAILY_TABLES = {'cb': 'tb_cb_daily', 'stock': 'tb_stock_daily'}
PRICE_COLUMNS = ('open', 'high', 'low', 'close')


def _path(database_path):
    path = Path(database_path)
    if not path.is_file():
        raise ValueError('supplied data lake is not an existing file')
    return path


def _fingerprint(path):
    digest = hashlib.sha256()
    try:
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return path.stat().st_size, digest.hexdigest()
    except OSError:
        raise ValueError('cannot read data lake fingerprint') from None


@contextmanager
def _snapshot(database_path):
    if duckdb is None:
        raise ValueError('DuckDB dependency is not installed; install the optional dev dependencies')
    path = _path(database_path)
    connection = None
    try:
        connection = duckdb.connect(str(path), read_only=True)
        connection.execute('SET enable_external_access = false')
        connection.execute('BEGIN TRANSACTION')
        yield connection
        connection.execute('COMMIT')
    except duckdb.Error:
        raise ValueError('read-only data lake query failed; schema or file access requires inspection') from None
    finally:
        if connection is not None:
            connection.close()


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}', value):
        raise ValueError('dates must be YYYYMMDD or YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('invalid calendar date') from None


def _date_sql(column):
    # Column is always one of the fixed adapter identifiers, never user text.
    return f"COALESCE(TRY_STRPTIME(CAST({column} AS VARCHAR), '%Y%m%d')::DATE, TRY_CAST({column} AS DATE))"


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _schema(connection):
    rows = connection.execute('''SELECT table_name,column_name,data_type FROM information_schema.columns
        WHERE table_schema='main' ORDER BY table_name,ordinal_position''').fetchall()
    schemas = {}
    base = {row[0] for row in connection.execute('''SELECT table_name FROM information_schema.tables
        WHERE table_schema='main' AND table_type='BASE TABLE' ''').fetchall()}
    for table, column, kind in rows:
        if table in TABLES and table in base:
            schemas.setdefault(table, {})[column] = kind
    return schemas


def _daily_quality(connection, table, schema):
    required = {'ts_code', 'trade_date', 'vol', *PRICE_COLUMNS}
    if not required.issubset(schema):
        return {'status': 'NOT_RUN', 'reason': 'missing required daily columns'}
    numeric = {column: f'TRY_CAST("{column}" AS DOUBLE)' for column in (*PRICE_COLUMNS, 'vol')}
    o, h, low, close, vol = (numeric[column] for column in (*PRICE_COLUMNS, 'vol'))
    placeholder = f'({o}=0 AND {h}=0 AND {low}=0 AND {vol}=0 AND {close}>0 AND ISFINITE({close}))'
    bad_price = ' OR '.join(f'({numeric[c]} IS NULL OR NOT ISFINITE({numeric[c]}))' for c in PRICE_COLUMNS)
    invalid = (f'({bad_price} OR {o}<=0 OR {h}<=0 OR {low}<=0 OR {close}<=0 '
               f'OR {h}<GREATEST({o},{close}) OR {low}>LEAST({o},{close}) OR {h}<{low})')
    values = connection.execute(f'''SELECT
        COUNT(*) FILTER(WHERE {placeholder}),
        COUNT(*) FILTER(WHERE ({invalid}) AND NOT COALESCE({placeholder},false)),
        COUNT(*) FILTER(WHERE {bad_price}),
        COUNT(*) FILTER(WHERE {vol}<0),
        COUNT(*) FILTER(WHERE ts_code IS NULL OR TRIM(CAST(ts_code AS VARCHAR))=''),
        COUNT(*) FILTER(WHERE {_date_sql('trade_date')} IS NULL),
        COUNT(*)-COUNT(DISTINCT (ts_code,trade_date)) FROM {table}''').fetchone()
    return dict(zip(('placeholder_rows', 'invalid_ohlc_rows', 'nonfinite_price_rows', 'negative_volume_rows',
                     'missing_symbol_rows', 'invalid_date_rows', 'duplicate_excess_rows'), map(int, values)))


def _paper_months():
    for year in range(2000, 2023):
        for month in range(1, 13):
            if (year, month) < (2000, 7) or (year, month) > (2022, 6):
                continue
            yield date(year, month, 1)


def _coverage(connection, schemas):
    cal = {}
    duplicates = set()
    if {'cal_date', 'is_open'}.issubset(schemas.get('tb_trade_cal', {})):
        for raw_day, is_open in connection.execute('SELECT cal_date,is_open FROM tb_trade_cal').fetchall():
            try:
                day = _day(raw_day)
            except ValueError:
                continue
            if day in cal:
                duplicates.add(day)
            if str(is_open).lower() in {'0', 'false', '1', 'true'}:
                cal[day] = str(is_open).lower() in {'1', 'true'}
    result = {}
    for asset, table in DAILY_TABLES.items():
        observed = {}
        if 'trade_date' in schemas.get(table, {}):
            for day, count in connection.execute(f'''SELECT {_date_sql('trade_date')} AS day,COUNT(*)
                FROM {table} GROUP BY day''').fetchall():
                if day is not None:
                    observed[day] = int(count)
        months = []
        for start in _paper_months():
            days = [start + timedelta(days=i) for i in range(calendar.monthrange(start.year, start.month)[1])]
            complete = all(day in cal and day not in duplicates for day in days)
            opened = {day for day in days if cal.get(day)} if complete else set()
            endpoint = max(opened) if opened else None
            months.append({'month': start.strftime('%Y-%m'), 'calendar_complete': complete,
                           'expected_monthend': _iso(endpoint),
                           'monthend_rows': observed.get(endpoint, 0) if endpoint else 0,
                           'expected_open_days': len(opened) if complete else None,
                           'observed_open_days': len(opened.intersection(observed)) if complete else None,
                           'all_open_dates_present': bool(opened) and opened.issubset(observed)})
        result[asset] = {'paper_months': len(months),
                         'calendar_complete_months': sum(m['calendar_complete'] for m in months),
                         'monthends_with_rows': sum(m['monthend_rows'] > 0 for m in months),
                         'all_open_dates_present_months': sum(m['all_open_dates_present'] for m in months),
                         'coverage_convention': 'aggregate dates only; no security-universe completeness claim',
                         'months': months}
    return result


def audit_lake(database_path):
    """Audit one consistent read transaction and compare database bytes around it."""
    path = _path(database_path)
    before_bytes, before_hash = _fingerprint(path)
    tables = {}
    with _snapshot(path) as connection:
        schemas = _schema(connection)
        for table in TABLES:
            if table not in schemas:
                tables[table] = {'status': 'MISSING', 'schema': {}, 'row_count': 0}
                continue
            schema = schemas[table]
            count = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            report = {'status': 'OBSERVED', 'schema': schema, 'row_count': int(count)}
            if 'ts_code' in schema:
                report['symbol_count'] = int(connection.execute(f'SELECT COUNT(DISTINCT ts_code) FROM {table}').fetchone()[0])
            date_column = 'trade_date' if 'trade_date' in schema else 'cal_date' if 'cal_date' in schema else None
            if date_column:
                minimum, maximum, distinct = connection.execute(f'''SELECT MIN({_date_sql(date_column)}),
                    MAX({_date_sql(date_column)}),COUNT(DISTINCT {_date_sql(date_column)}) FROM {table}''').fetchone()
                report.update(date_min=_iso(minimum), date_max=_iso(maximum), date_count=int(distinct))
            if table in DAILY_TABLES.values():
                report['quality'] = _daily_quality(connection, table, schema)
            tables[table] = report
        coverage = _coverage(connection, schemas)
    after_bytes, after_hash = _fingerprint(path)
    requirements = {
        'paper_market_panel': {'status': 'INSUFFICIENT', 'reason':
            'Requires matched monthend bond/stock coverage from 2000-07 through 2022-06 and paper exclusions; '
            'aggregate raw bars alone do not establish the 696-bond/14980-observation sample.'},
        'stock_volatility_lookback': {'status': 'UNVERIFIED', 'reason':
            'Requires at least 250 prior valid stock returns at every valuation plus validated adjustment history; '
            'mapped raw bars have no adjustment-event dataset.'},
        'maturity_coupon_schedule': {'status': 'MISSING', 'reason':
            'Mapped master has no maturity date, full stepped coupon schedule, face/redemption terms or payment events.'},
        'historical_conversion_events': {'status': 'MISSING', 'reason':
            'Current cb_basic.conv_price is not a dated conversion-price event history and is never backfilled.'},
        'historical_clauses': {'status': 'MISSING', 'reason':
            'No mapped historical call/put/reset windows, legal floors, waivers or amendments.'},
        'treasury_spot_curves': {'status': 'MISSING', 'reason':
            'No mapped historical Chinese treasury spot term structure; YTM or a constant is not substituted.'},
        'deposit_risk_free': {'status': 'MISSING', 'reason':
            'No mapped effective-dated one-year deposit rate for portfolio excess returns.'},
        'financial_factors': {'status': 'MISSING', 'reason':
            'No mapped PIT financial series or paper-matching Carhart4/FF5/HXZ4/SY4/DHS3 factor-return libraries.'},
        'coupon_terminal_returns': {'status': 'MISSING', 'reason':
            'Raw pct_chg does not establish coupon-inclusive total returns, redemption/put proceeds or terminal months.'},
    }
    cb = tables.get('tb_cb_daily', {})
    stock = tables.get('tb_stock_daily', {})
    if stock.get('date_count', 0) < 251:
        requirements['stock_volatility_lookback']['status'] = 'INSUFFICIENT'
        requirements['stock_volatility_lookback']['reason'] = (
            f"Only {stock.get('date_count', 0)} distinct stock-bar dates observed; at least250prior return observations "
            'plus a starting price and adjustment validation are required at each valuation.')
    stable = before_bytes == after_bytes and before_hash == after_hash
    return {'database': {'name': path.name, 'read_only': True, 'consistent_transaction': True,
                         'bytes_before': before_bytes, 'bytes_after': after_bytes,
                         'sha256_before': before_hash, 'sha256_after': after_hash, 'stable': stable},
            'tables': tables, 'month_end_coverage': coverage, 'paper_requirements': requirements,
            'fully_qualified': False, 'research_status': 'not_evaluated',
            'summary': {'cb_bar_rows': cb.get('row_count', 0), 'stock_bar_rows': stock.get('row_count', 0),
                        'warning': 'Local raw-data engineering audit only; no pricing, alpha or strategy result.'}}


def read_daily_bars(database_path, asset='cb', symbols=None, start=None, end=None):
    """Return unmodified bars from a fixed table using parameterized filters."""
    if not isinstance(asset, str) or asset not in DAILY_TABLES:
        raise ValueError('asset must be cb or stock')
    if symbols is not None and (not isinstance(symbols, (list, tuple)) or any(
            not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol) for symbol in symbols)):
        raise ValueError('symbols must be a list of exchange-qualified six-digit codes')
    first, last = _day(start) if start is not None else None, _day(end) if end is not None else None
    if first and last and first > last:
        raise ValueError('start date must not follow end date')
    if symbols is not None and not symbols:
        return []
    filters, parameters = [], []
    if symbols:
        filters.append('ts_code IN (' + ','.join('?' for _ in symbols) + ')')
        parameters.extend(symbols)
    for bound, comparator in ((first, '>='), (last, '<=')):
        if bound:
            filters.append(_date_sql('trade_date') + comparator + '?')
            parameters.append(bound)
    query = f'SELECT * FROM {DAILY_TABLES[asset]}'
    if filters:
        query += ' WHERE ' + ' AND '.join(filters)
    query += ' ORDER BY trade_date,ts_code'
    with _snapshot(database_path) as connection:
        cursor = connection.execute(query, parameters)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, (_iso(value) for value in row))) for row in cursor.fetchall()]


def capability_report(database_path):
    """Expose verified local capabilities and unresolved requirements, not a fake dataset."""
    report = audit_lake(database_path)
    return {'database': report['database'], 'summary': report['summary'],
            'fully_qualified': report['fully_qualified'], 'research_status': report['research_status'],
            'paper_requirements': report['paper_requirements']}


def build_paper_dataset(database_path):
    report = capability_report(database_path)
    missing = [name for name, requirement in report['paper_requirements'].items()
               if requirement['status'] != 'QUALIFIED']
    raise ValueError('paper dataset cannot be built from mapped lake tables; unresolved requirements: '
                     + ', '.join(missing))
