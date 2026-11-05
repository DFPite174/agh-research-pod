"""Bounded, explicit raw-price contracts for the selected A-share account engine."""
import csv
import hashlib
import io
import json
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path


def read_bounded(path, maximum=25_000_000):
    with Path(path).open('rb') as stream:
        content = stream.read(maximum+1)
    if len(content) > maximum:
        raise ValueError('research input exceeds byte budget')
    return content


def records(content):
    parsed = csv.reader(io.StringIO(content.decode('utf-8-sig')), strict=True)
    header = next(parsed, [])
    if not header or len(header) != len(set(header)):
        raise ValueError('CSV header must be nonempty and unique')
    rows = []
    for row in parsed:
        if not row:
            continue
        if len(row) != len(header):
            raise ValueError('CSV field count differs from header')
        rows.append(dict(zip(header, row)))
        if len(rows) > 20000:
            raise ValueError('equity dataset exceeds 20000 records')
    return rows


def load_equity_dataset(manifest_path):
    path = Path(manifest_path).resolve()
    raw = read_bounded(path, 1_000_000)
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError('equity manifest must be an object')
    for key in ('source', 'license', 'limitations'):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError('equity manifest requires source, license and limitations')
    if manifest.get('price_mode') != 'raw' or manifest.get('evidence_level') not in {'synthetic', 'alternative_real'}:
        raise ValueError('explicit raw price_mode and evidence_level required')
    if type(manifest.get('volume_multiplier')) is not int or manifest['volume_multiplier'] not in (1, 100):
        raise ValueError('explicit volume_multiplier must be 1 (shares) or 100 (lots)')
    files = {}
    for key in ('bars_csv', 'rules_csv', 'calendar_csv'):
        name = manifest.get(key)
        if not isinstance(name, str):
            raise ValueError('bars_csv, rules_csv and calendar_csv required')
        target = (path.parent/name).resolve()
        if not target.is_relative_to(path.parent) or target == path.parent:
            raise ValueError('equity file escapes dataset root')
        files[key] = read_bounded(target)
    bars, rules, calendar = [records(files[k]) for k in ('bars_csv', 'rules_csv', 'calendar_csv')]
    days = [date.fromisoformat(r['date']).isoformat() for r in calendar]
    if not days or days != sorted(set(days)) or any(date.fromisoformat(d).weekday() >= 5 for d in days):
        raise ValueError('calendar must be unique ordered exchange weekdays')
    instruments = manifest.get('instruments')
    if not isinstance(instruments, list) or not 1 <= len(instruments) <= 50:
        raise ValueError('1..50 explicit instruments required')
    symbols = [i['symbol'] for i in instruments]
    if len(set(symbols)) != len(symbols) or any(not s.endswith(('.SH', '.SZ')) for s in symbols):
        raise ValueError('unique Shanghai/Shenzhen symbols required')
    converted_bars, converted_rules = [], []
    seen = set()
    for row in bars:
        symbol, day = row['symbol'], date.fromisoformat(row['date']).isoformat()
        if (symbol, day) in seen or symbol not in symbols or day not in days:
            raise ValueError('duplicate or out-of-contract equity bar')
        seen.add((symbol, day))
        prices = {k: Decimal(row[k]) for k in ('open', 'high', 'low', 'close')}
        volume = Decimal(row['volume'])*manifest['volume_multiplier']
        if any(not p.is_finite() or p <= 0 for p in prices.values()) or not volume.is_finite() or volume < 0 or volume != int(volume):
            raise ValueError('invalid raw price or integer share volume')
        converted_bars.append({'symbol': symbol, 'start': day+'T09:30:00+08:00', 'end': day+'T15:00:00+08:00',
                               **{k: str(v) for k, v in prices.items()}, 'volume': int(volume)})
    rule_keys = set()
    for row in rules:
        symbol, day = row['symbol'], date.fromisoformat(row['date']).isoformat()
        if (symbol, day) in rule_keys or symbol not in symbols or day not in days:
            raise ValueError('duplicate or out-of-contract daily rule')
        rule_keys.add((symbol, day))
        rule = {k: row[k] for k in ('trade_status', 'limit_state')}
        for k in ('buy_min', 'buy_step', 'sell_min', 'sell_step', 'max_order'):
            rule[k] = int(row[k])
        for k in ('down_limit', 'up_limit'):
            if row.get(k):
                value = Decimal(row[k])
                if not value.is_finite():
                    raise ValueError('daily price limit must be finite')
                rule[k] = float(value)
        converted_rules.append({'symbol': symbol, 'date': day, 'rule': rule})
    if rule_keys != {(s, d) for s in symbols for d in days}:
        raise ValueError('daily rules must cover every symbol and session')
    if not converted_bars:
        raise ValueError('equity bars empty')
    actions = manifest.get('corporate_actions', [])
    if not isinstance(actions, list):
        raise ValueError('corporate_actions must be explicit list')
    snapshot = {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                **{k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
    request = {'asset_class': 'EQUITY', 'instruments': instruments, 'bars': converted_bars,
               'rules': converted_rules, 'trading_days': days, 'corporate_actions': actions}
    return {'request': request, 'snapshot': snapshot, 'manifest': manifest,
            'attachments': {'dataset-manifest.json': raw, **{k+'.csv': v for k, v in files.items()}},
            'summary': {'sessions': len(days), 'symbols': symbols, 'bars': len(bars),
                        'start': days[0], 'end': days[-1], 'source': manifest['source'],
                        'evidence_level': manifest['evidence_level'], 'limitations': manifest['limitations']}}


def default_astock_root():
    configured = os.getenv('AGH_ASTOCKDB_ROOT')
    if configured:
        return configured
    workspace = Path.home()/'Downloads'/'MyProj'/'my_upload'/'AStockDB_V0_2'
    for candidate in (workspace, workspace/'AStockDB_V0_2'):
        if (candidate/'db'/'astock.duckdb').is_file() and (candidate/'astockdb').is_dir():
            return str(candidate)
    raise ValueError('AStockDB not found; configure AGH_ASTOCKDB_ROOT or supply a prepared manifest')


def prepare_astock_dataset(data_root, output, symbols, start, end):
    """Read-only standard data preparation; never download or repair a source database."""
    import duckdb
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols)
            or any(not isinstance(s, str) or not re.fullmatch(r'(?:60\d{4}\.SH|00\d{4}\.SZ)', s) for s in symbols)):
        raise ValueError('initial preparation supports 1..10 explicit main-board Shanghai/Shenzhen stocks')
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('reversed data window')
    database = Path(data_root)/'db'/'astock.duckdb'
    if not database.is_file():
        raise ValueError('configured AStockDB root missing')
    connection = duckdb.connect(str(database), read_only=True)
    try:
        connection.execute('SET allowed_directories = ?', [[str(Path(data_root).resolve()/'data')]])
        connection.execute('SET enable_external_access=false')
        connection.execute('BEGIN TRANSACTION')
        marks = ','.join('?' for _ in symbols)
        frame = connection.execute(f'''SELECT symbol,date,raw_open AS open,raw_high AS high,
            raw_low AS low,raw_close AS close,volume,limit_up,limit_down,tradable,is_suspended,
            no_price_limit,rule_confidence FROM research_daily
            WHERE symbol IN ({marks}) AND date BETWEEN ? AND ? ORDER BY date,symbol LIMIT 20001''',
            [*symbols, start, end]).df()
        calendar = connection.execute('SELECT date FROM trading_calendar WHERE date BETWEEN ? AND ? ORDER BY date', [start, end]).df()
        connection.execute('COMMIT')
    finally:
        connection.close()
    if frame.empty or len(frame) > 20000 or calendar.empty:
        raise ValueError('empty or oversized AStockDB research window')
    frame['date'] = frame.date.dt.strftime('%Y-%m-%d')
    calendar['date'] = calendar.date.dt.strftime('%Y-%m-%d')
    expected = {(s, d) for s in symbols for d in calendar.date}
    if set(zip(frame.symbol, frame.date)) != expected:
        raise ValueError('source lacks explicit daily rows; cannot infer suspension or missing data')
    rules = []
    for row in frame.to_dict('records'):
        status = 'SUSPENDED' if row['is_suspended'] else ('OPEN' if row['tradable'] else 'DAY_BLOCKED')
        rules.append({'symbol': row['symbol'], 'date': row['date'], 'trade_status': status,
                      'limit_state': 'UNBOUNDED' if row['no_price_limit'] else 'BOUNDED',
                      'down_limit': row['limit_down'], 'up_limit': row['limit_up'],
                      'buy_min': 100, 'buy_step': 100, 'sell_min': 100, 'sell_step': 100, 'max_order': 1000000})
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Suspended/day-blocked records remain explicit in rules; do not fabricate price bars.
    bars = frame[frame.tradable][['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]
    bars.to_csv(directory/'bars.csv', index=False)
    import pandas as pd
    pd.DataFrame(rules).to_csv(directory/'rules.csv', index=False)
    calendar.to_csv(directory/'calendar.csv', index=False)
    manifest = {'bars_csv': 'bars.csv', 'rules_csv': 'rules.csv', 'calendar_csv': 'calendar.csv',
                'source': 'AStockDB read-only research_daily and trading_calendar snapshot',
                'license': 'Private user-authorized research data; do not redistribute without source permission',
                'limitations': 'Historical raw prices/rule regimes; PIT revisions and corporate-event completeness not independently qualified. No event table exported; not complete total-return evidence.',
                'price_mode': 'raw', 'volume_multiplier': 1, 'evidence_level': 'alternative_real',
                'instruments': [{'symbol': s, 'exchange': 'SSE' if s.endswith('.SH') else 'SZSE'} for s in symbols],
                'corporate_actions': [], 'preparation': {'symbols': symbols, 'start': start, 'end': end,
                 'rule_confidence_counts': frame.rule_confidence.value_counts().to_dict(),
                 'automatic_price_repair': False, 'database_read_only': True}}
    manifest_path = directory/'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    load_equity_dataset(manifest_path)
    return str(manifest_path)
