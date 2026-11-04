import pytest
from agh_pod.strategy_rules import validate_rule, evaluate_rule


def test_strategy_rules_are_safe_and_historical_only():
    history=[{'close':float(x),'open':float(x),'high':float(x),'low':float(x),'volume':10000} for x in range(1,8)]
    assert evaluate_rule('close > sma(close, 3) and ret(close, 2) > 0',history)
    assert not evaluate_rule('close > sma(close, 20)',history)
    for expression in ["__import__('os').system('whoami')",'close.__class__','lag(close, -1)','sma(close, 99999)']:
        with pytest.raises(ValueError): validate_rule(expression)

def test_native_equity_adapter_routes_only_to_selected_engine(tmp_path):
    import json,subprocess
    from agh_pod.backends.nautilus import run_equity_backtest
    def process(args,**kw):
        payload=json.loads(kw['input'])
        assert payload['action']=='equity' and payload['asset_class']=='EQUITY'
        return subprocess.CompletedProcess(args,0,'AGH_RESULT='+json.dumps({'status':'EXECUTED_NOT_QUALIFIED','result':{}}),'')
    assert run_equity_backtest(tmp_path,{'asset_class':'EQUITY'},process=process)['status']=='EXECUTED_NOT_QUALIFIED'


def test_evaluator_requires_native_reconciliation():
    from agh_pod.research_agent import evaluate_account
    with pytest.raises(ValueError,match='reconcil'):
        evaluate_account({'native_cash':'100','ledger_cash':'99','daily_nav':[]},100)
import json
import httpx
from agh_pod.workflow import Pod


def dataset_fixture(tmp_path,n=100):
    import pandas as pd
    days=pd.bdate_range('2024-01-02',periods=n)
    bars=[{'symbol':'600000.SH','date':d.date().isoformat(),'open':10.,'high':10.1,'low':9.9,'close':10.,'volume':1000000} for d in days]
    rules=[{'symbol':'600000.SH','date':r['date'],'trade_status':'OPEN','limit_state':'BOUNDED','down_limit':1.,'up_limit':100.,'buy_min':100,'buy_step':100,'sell_min':100,'sell_step':100,'max_order':100000} for r in bars]
    pd.DataFrame(bars).to_csv(tmp_path/'bars.csv',index=False);pd.DataFrame(rules).to_csv(tmp_path/'rules.csv',index=False)
    pd.DataFrame({'date':[r['date'] for r in bars]}).to_csv(tmp_path/'calendar.csv',index=False)
    m={'bars_csv':'bars.csv','rules_csv':'rules.csv','calendar_csv':'calendar.csv','source':'synthetic fixture','license':'generated','limitations':'engineering only','price_mode':'raw','volume_multiplier':1,'evidence_level':'synthetic','instruments':[{'symbol':'600000.SH','exchange':'SSE'}],'corporate_actions':[]}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(m));return path


def plan(evidence):
    return {'hypothesis':'test close versus mean','evidence_ids':[evidence],'assumptions':['synthetic engineering'],'adaptation':'cash long only','buy':'close > sma(close, 3)','sell':'close < sma(close, 3)','rationale':'fixed method','unsupported_reason':''}


def native_backend(root,request,**kw):
    days=request['trading_days']; cash=request['initial_cash']
    return {'status':'EXECUTED_NOT_QUALIFIED','result':{'native_cash':str(cash),'ledger_cash':str(cash),'daily_nav':[{'date':d,'total_equity':str(cash),'cash_matches':True,'positions_match':True} for d in days], 'fills':[]}}


def setup_task(tmp_path,**kwargs):
    from agh_pod.research_agent import create_research
    m=dataset_fixture(tmp_path);pod=Pod(tmp_path/'pod');a=pod.add_artifact('manual','research source',b'Buy when price exceeds its past mean. Sell below mean.')
    task=create_research(pod,{'title':'AI research','goal':'validate source in A shares','artifact_ids':[a['id']],'dataset':str(m),**kwargs})
    return pod,a,task


def test_controlled_model_iteration_has_fixed_engine_and_no_holdout_feedback(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture-key');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path)
    calls=[]
    def reply(req):
        body=json.loads(req.content);prompt=json.loads(body['messages'][1]['content'])
        assert 'holdout' not in json.dumps(prompt['development_feedback'])
        calls.append(body)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}],'usage':{'total_tokens':100}})
    result=run_research(pod,task['id'],engine_root='operator-configured-engine',client=httpx.Client(transport=httpx.MockTransport(reply)),backend=native_backend)
    assert result['status']=='COMPLETED_NEGATIVE'
    assert result['calls']==2 and len(result['attempt_ids'])==2
    assert not result['holdout_used_once']
    assert result['engine_repository'].endswith('ashare-nautilus-backtest-engine')
    assert all('holdout' not in body['messages'][1]['content'].split('development_feedback')[1] for body in calls)


def test_budget_exhaustion_never_calls_provider(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture-key');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path,max_total_tokens=2000)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:pytest.fail('budget violation reached provider')))
    result=run_research(pod,task['id'],engine_root='engine',client=client,backend=native_backend)
    assert result['status']=='BUDGET_EXHAUSTED' and result['calls']==0


def test_frozen_task_rejects_changed_data(tmp_path):
    from agh_pod.research_agent import run_research
    pod,a,task=setup_task(tmp_path)
    with (tmp_path/'bars.csv').open('a') as f: f.write('bad')
    result=run_research(pod,task['id'],engine_root='engine',backend=native_backend)
    assert result['status']=='FAILED'

def test_research_export_is_self_contained_and_rejects_missing_data(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research,export_research
    from agh_pod.equity_data import load_equity_dataset
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture-key');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path,max_rounds=1)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}]})))
    run_research(pod,task['id'],engine_root='engine',client=client,backend=native_backend)
    package=export_research(pod,task['id']);p=__import__('pathlib').Path(package['path'])
    assert pod.verify_package(p)['valid']
    assert load_equity_dataset(p/'dataset-manifest.json')['request']['trading_days']
    m=json.loads((p/'manifest.json').read_text());m['files'].pop('bars.csv');(p/'manifest.json').write_text(json.dumps(m))
    assert not pod.verify_package(p)['valid']


def test_failed_final_engine_check_is_not_completed_research(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture-key');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path,max_rounds=1)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}]})))
    def backend(root,request,**kw):
        if request.get('signal_start'): return {'status':'FAILED'}
        response=native_backend(root,request,**kw)
        if request['strategy']['buy']!='True':
            response['result']['fills']=[{'fee':'1'}]
            for row in response['result']['daily_nav']: row['total_equity']=str(request['initial_cash']*1.01)
        return response
    r=run_research(pod,task['id'],engine_root='engine',client=client,backend=backend)
    assert r['status']=='BLOCKED_BACKTEST'


def test_manual_research_api_returns_persisted_task(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    monkeypatch.delenv('AGH_BACKTEST_ENGINE_ROOT',raising=False)
    dataset=dataset_fixture(tmp_path);app=create_app(tmp_path/'api');a=app.state.pod.add_artifact('manual','source',b'test source')
    with TestClient(app) as c:
        r=c.post('/v1/research',json={'title':'research','goal':'test source','artifact_ids':[a['id']],'dataset':str(dataset)})
        assert r.status_code==202,r.text
        detail=c.get('/v1/research/'+r.json()['id']).json()
        assert detail['status']=='BLOCKED_ENGINE_CONFIGURATION'
        assert c.get('/v1/research').json()[0]['id']==r.json()['id']
        assert 'research-form' in c.get('/').text

def test_passing_candidate_is_selected_before_higher_return_failed_candidate(tmp_path,monkeypatch):
    import agh_pod.research_agent as research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path)
    count=[0];holdout=[]
    def reply(_):
        count[0]+=1;p=plan(a['id']);p['rationale']=str(count[0])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(p)}}]})
    def pair(task,dataset,p,*args,final=False):
        if final: holdout.append(p['rationale'])
        passed=p['rationale']=='2'
        return {'status':'EVALUATED','excess_return':.10 if passed else .15,'meets_fixed_thresholds':passed,'sample_adequate':True,'runs':{'candidate':{'metrics':{'max_drawdown':.1 if passed else .4}},'baseline':{'metrics':{}}}}
    monkeypatch.setattr(research,'_backtest_pair',pair)
    r=research.run_research(pod,task['id'],engine_root='engine',client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert holdout==['2']
    assert pod.get('research_attempt',r['selected_attempt'])['plan']['rationale']=='2'


def test_provider_token_overrun_stops_before_backtest_or_second_call(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path);calls=[]
    def reply(req):
        calls.append(req)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}],'usage':{'total_tokens':999999}})
    r=run_research(pod,task['id'],engine_root='engine',client=httpx.Client(transport=httpx.MockTransport(reply)),backend=lambda *a,**kw:pytest.fail('overrun reached backtest'))
    assert r['status']=='PROVIDER_BUDGET_OVERRUN' and len(calls)==1

def test_implementation_change_invalidates_triggered_task(tmp_path,monkeypatch):
    import agh_pod.research_agent as research
    pod,a,task=setup_task(tmp_path)
    monkeypatch.setattr(research,'implementation_snapshot',lambda:{'changed':'implementation'})
    result=research.run_research(pod,task['id'],engine_root='engine',backend=native_backend)
    assert result['status']=='FAILED' and result['error_type']=='IntegrityError'


def test_missing_model_usage_is_explicitly_unknown(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path,max_rounds=1)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}]})))
    result=run_research(pod,task['id'],engine_root='engine',client=client,backend=native_backend)
    assert result['unknown_usage_calls']==1 and result['reported_tokens_known']==0
    assert result['reserved_tokens']>0


def test_supplied_astock_preparation_is_bounded_and_operator_configured(tmp_path,monkeypatch):
    import agh_pod.research_agent as research
    manifest=dataset_fixture(tmp_path);pod=Pod(tmp_path/'prepared-pod');a=pod.add_artifact('manual','source',b'method')
    monkeypatch.setenv('AGH_ASTOCKDB_ROOT','operator-only-root')
    calls=[]
    def prepare(root,output,**kw):
        calls.append((root,kw));return str(manifest)
    monkeypatch.setattr(research,'prepare_astock_dataset',prepare)
    task=research.create_research(pod,{'title':'data tool','goal':'test','artifact_ids':[a['id']],'data_request':{'symbols':['600000.SH'],'start':'2024-01-02','end':'2024-05-31'}})
    assert calls[0][0]=='operator-only-root' and task['dataset_snapshot']


def test_equity_rule_price_bands_are_numeric(tmp_path):
    from agh_pod.equity_data import load_equity_dataset
    m=dataset_fixture(tmp_path)
    data=load_equity_dataset(m)
    assert isinstance(data['request']['rules'][0]['rule']['up_limit'],float)

def test_unsupported_method_is_not_silently_replaced_by_backtest(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path);p=plan(a['id']);p['unsupported_reason']='Requires short selling and unsupported derivatives'
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(p)}}]})))
    r=run_research(pod,task['id'],engine_root='engine',client=client,backend=lambda *a,**kw:pytest.fail('unsupported method reached engine'))
    assert r['status']=='BLOCKED_METHOD'


def test_rejected_citation_is_preserved_as_failed_attempt(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path);p=plan('invented-evidence')
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(p)}}]})))
    r=run_research(pod,task['id'],engine_root='engine',client=client,backend=lambda *a,**kw:pytest.fail('bad citation reached engine'))
    assert r['status']=='FAILED'
    assert pod.get('research_attempt',r['attempt_ids'][0])['status']=='REJECTED_EVIDENCE'

def test_provider_usage_metadata_does_not_echo_arbitrary_fields(tmp_path,monkeypatch):
    from agh_pod.research_agent import run_research
    monkeypatch.setenv('AGH_LLM_API_KEY','fixture-key');monkeypatch.setenv('AGH_LLM_MODEL','fixture')
    pod,a,task=setup_task(tmp_path,max_rounds=1)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan(a['id']))}}],'usage':{'total_tokens':100,'debug':'fixture-key'}})))
    r=run_research(pod,task['id'],engine_root='engine',client=client,backend=native_backend)
    attempt=pod.get('research_attempt',r['attempt_ids'][0])
    assert 'fixture-key' not in json.dumps(attempt)
