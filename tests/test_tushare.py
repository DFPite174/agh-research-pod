import json
from pathlib import Path

import httpx

from agh_pod.providers.tushare import PROBES, probe_tushare


def test_no_token_no_network(monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN',raising=False)
    def reply(request):
        raise AssertionError('must not call without token')
    result = probe_tushare(client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert result['status'] == 'NOT_RUN'
    assert result['probes'] == []


def test_probe_outputs_summary_without_credentials_or_rows(monkeypatch):
    monkeypatch.setenv('TUSHARE_TOKEN','secret-token')
    calls = []
    def reply(request):
        assert str(request.url) == 'https://api.tushare.pro'
        body = json.loads(request.content)
        assert body['token'] == 'secret-token'
        calls.append(body)
        if body['api_name'] == 'cb_price_chg':
            return httpx.Response(200,json={'code':-2002,'msg':'secret-token no permission'})
        return httpx.Response(200,json={'code':0,'data':{'fields':['trade_date','ts_code'],
                                                       'items':[['20000703','private-row']]}})
    result = probe_tushare(client=httpx.Client(transport=httpx.MockTransport(reply)))
    serialized = json.dumps(result)
    assert 'secret-token' not in serialized and 'private-row' not in serialized
    assert result['status'] == 'QUALIFICATION_INCOMPLETE'
    assert any(p['row_count'] == 1 and p['min_date'] == '20000703' for p in result['probes'])
    assert any(p['outcome'] == 'PERMISSION_DENIED' for p in result['probes'])
    assert len(calls) <= 12


def test_probe_empty_results_are_not_qualified(monkeypatch):
    monkeypatch.setenv('TUSHARE_TOKEN','secret')
    transport = httpx.MockTransport(lambda request: httpx.Response(200,json={
        'code':0,'data':{'fields':['trade_date'],'items':[]}}))
    result = probe_tushare(client=httpx.Client(transport=transport))
    assert result['status'] == 'QUALIFICATION_INCOMPLETE'
    assert all(probe['outcome'] == 'EMPTY' for probe in result['probes'])


def test_reviewable_probe_manifest_matches_runtime():
    manifest = Path(__file__).parents[1] / 'configs' / 'tushare-probes.json'
    assert manifest.exists(), 'explicit probe manifest missing'
    assert json.loads(manifest.read_text(encoding='utf-8'))['probes'] == PROBES
