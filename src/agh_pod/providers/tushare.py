"""Small explicit entitlement probes; never publish provider rows or credentials."""

import json
import os
import re

import httpx

from ..sources import _request


PROBES = [
    {'name': 'old_bond_metadata', 'api_name': 'cb_basic', 'params': {'ts_code': '110001.SH'},
     'fields': 'ts_code,list_date,delist_date,value_date,maturity_date,call_clause,put_clause,reset_clause'},
    {'name': 'early_bond_prices', 'api_name': 'cb_daily',
     'params': {'ts_code': '110001.SH', 'start_date': '20000701', 'end_date': '20000731'},
     'fields': 'ts_code,trade_date,close'},
    {'name': 'old_coupon_schedule', 'api_name': 'cb_rate', 'params': {'ts_code': '110001.SH'},
     'fields': 'ts_code,rate_start_date,rate_end_date,coupon_rate,rate_freq'},
    {'name': 'conversion_history', 'api_name': 'cb_price_chg', 'params': {'ts_code': '110001.SH'},
     'fields': 'ts_code,publish_date,change_date,convertprice_bef,convertprice_aft'},
    {'name': 'early_call_events', 'api_name': 'cb_call',
     'params': {'start_date': '20000101', 'end_date': '20041231'},
     'fields': 'ts_code,ann_date,call_date,call_price,payment_date'},
    {'name': 'early_spot_curve', 'api_name': 'yc_cb',
     'params': {'ts_code': '1001.CB', 'curve_type': '1', 'trade_date': '20000731', 'curve_term': 1},
     'fields': 'trade_date,curve_type,curve_term,yield'},
    {'name': 'recent_spot_curve', 'api_name': 'yc_cb',
     'params': {'ts_code': '1001.CB', 'curve_type': '1', 'trade_date': '20220630', 'curve_term': 1},
     'fields': 'trade_date,curve_type,curve_term,yield'},
    {'name': 'early_stock_prices', 'api_name': 'daily',
     'params': {'ts_code': '600001.SH', 'start_date': '20000701', 'end_date': '20000731'},
     'fields': 'ts_code,trade_date,close'},
    {'name': 'early_announcements', 'api_name': 'anns_d',
     'params': {'ts_code': '600001.SH', 'start_date': '20000701', 'end_date': '20000731'},
     'fields': 'ts_code,ann_date,title'},
]


class TushareProvider:
    def __init__(self, *, client=None):
        self.client = client

    def probe(self):
        return probe_tushare(client=self.client)


def probe_tushare(*, client=None):
    token = os.getenv('TUSHARE_TOKEN')
    result = {'status': 'NOT_RUN', 'probes': [], 'empirical_access_verified': False,
              'paper_coverage_verified': False}
    if not token:
        return {**result, 'reason': 'TUSHARE_TOKEN is not configured; no provider calls made.'}
    owned = client is None
    client = client or httpx.Client()
    try:
        for probe in PROBES:
            summary = {'name': probe['name'], 'api_name': probe['api_name'], 'outcome': 'ERROR',
                       'row_count': None, 'min_date': None, 'max_date': None}
            try:
                response = json.loads(_request(client, 'POST', 'https://api.tushare.pro',
                                               attempts=1, max_bytes=2_000_000,
                                               json={'token': token, **{k: probe[k] for k in
                                                     ('api_name', 'params', 'fields')}}))
                if not isinstance(response, dict):
                    raise ValueError('invalid provider container')
                code = response.get('code')
                if code != 0:
                    summary['outcome'] = 'PERMISSION_DENIED' if code in {-2002, 2002} else 'PROVIDER_ERROR'
                else:
                    data = response['data']
                    fields, rows = data['fields'], data['items']
                    if (not isinstance(fields, list) or not isinstance(rows, list)
                            or any(not isinstance(row, list) or len(row) != len(fields) for row in rows)):
                        raise ValueError('invalid provider shape')
                    dates = [str(row[i]).replace('-', '') for row in rows for i, field in enumerate(fields)
                             if isinstance(field, str) and field.endswith('date')
                             and re.fullmatch(r'\d{8}', str(row[i]).replace('-', ''))]
                    summary.update(outcome='OBSERVED' if rows else 'EMPTY', row_count=len(rows),
                                   min_date=min(dates) if dates else None, max_date=max(dates) if dates else None)
            except (ValueError, KeyError, TypeError):
                pass
            result['probes'].append(summary)
        result['empirical_access_verified'] = any(p['outcome'] == 'OBSERVED' for p in result['probes'])
        result['status'] = 'QUALIFICATION_INCOMPLETE'
        result['reason'] = 'Small entitlement samples do not establish full paper-period coverage or PIT quality.'
        return result
    finally:
        if owned:
            client.close()
