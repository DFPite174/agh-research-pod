import json
import numpy as np
import pandas as pd
import pytest
from agh_pod.quant import execute_quant, snapshot_dataset
from agh_pod.workflow import Pod


def dataset(tmp_path):
    p = tmp_path / "data.csv"
    n = 90
    pd.DataFrame({"date": pd.date_range("2000-01-01", periods=n, freq="MS"), "x": np.arange(n), "y": np.sin(np.arange(n)/5)}).to_csv(p,index=False)
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"csv":"data.csv","source":"test fixture","license":"generated","evidence_level":"synthetic","limitations":"not market observations"}))
    return m


def payload(m):
    return {"recipe":"quant","dataset":str(m),"target":"y","features":["x","y"],"min_train":24,"ridge":1.0}


def test_future_changes_do_not_change_past_predictions(tmp_path):
    m=dataset(tmp_path)
    a=execute_quant(payload(m))
    p=tmp_path/'data.csv'
    df=pd.read_csv(p); df.loc[75:,['x','y']]=999; df.to_csv(p,index=False)
    b=execute_quant(payload(m))
    assert a['predictions'][:40] == b['predictions'][:40]
    assert len(a['predictions']) == 65
    assert a['evidence_level']=='synthetic'
    assert a['research_status']=='not_evaluated'


def test_dates_and_nonfinite_rejected(tmp_path):
    m=dataset(tmp_path); p=tmp_path/'data.csv'
    df=pd.read_csv(p); df.loc[2,'date']=df.loc[1,'date']; df.to_csv(p,index=False)
    with pytest.raises(ValueError,match='date'): execute_quant(payload(m))


def test_quant_approval_detects_csv_change(tmp_path):
    m=dataset(tmp_path); pod=Pod(tmp_path/'pod')
    op=pod.create_opportunity('Quant','investment_research')
    s=pod.create_spec(op['id'],payload(m)); pod.approve(s['id'])
    with (tmp_path/'data.csv').open('a') as f: f.write('2099-01-01,1,2\n')
    r=pod.run_spec(s['id'])
    assert r['status']=='failed' and r['error_type']=='IntegrityError'


def test_real_data_requires_limitations(tmp_path):
    m=dataset(tmp_path); obj=json.loads(m.read_text()); obj['evidence_level']='alternative_real'; obj.pop('limitations'); m.write_text(json.dumps(obj))
    with pytest.raises(ValueError): snapshot_dataset(m)

def test_mandate_delivery_and_package(tmp_path):
    m=dataset(tmp_path); pod=Pod(tmp_path/'pod')
    op=pod.create_opportunity('Macro forecast','investment_research')
    pod.set_mandate(op['id'], {'objective':'test forecasts','baseline':'historical mean','acceptance':'compare OOS MSE','stop_condition':'one frozen run','receiver':'research'})
    s=pod.create_spec(op['id'],payload(m)); pod.approve(s['id']); r=pod.run_spec(s['id'])
    pod.review(r['id'],'local check','engineering_verified'); pack=pod.export_package(r['id'])
    feedback=pod.receive_package(pack['id'],'research','accepted','reusable method; no alpha claim')
    assert feedback['decision']=='accepted'
    assert pod.get('opportunity',op['id'])['status']=='received'
    assert pod.verify_package(pack['path'])['valid']
    assert pod.get('spec',s['id'])['mandate']['objective']=='test forecasts'

def test_api_quant_full_loop(tmp_path):
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    m=dataset(tmp_path)
    with TestClient(create_app(tmp_path/'api')) as c:
        op=c.post('/v1/opportunities',json={'title':'Forecast','research_type':'investment_research'}).json()
        mandate={'objective':'forecast','baseline':'mean','acceptance':'MSE','stop_condition':'one run','receiver':'research'}
        assert c.post('/v1/opportunities/'+op['id']+'/mandate',json=mandate).status_code==200
        s=c.post('/v1/opportunities/'+op['id']+'/specs',json=payload(m)).json()
        assert 'id' in s, s
        assert c.post('/v1/specs/'+s['id']+'/approve',json={}).status_code==200
        r=c.post('/v1/specs/'+s['id']+'/runs',json={}).json()
        assert c.get('/v1/runs/'+r['id']).json()['status']=='succeeded'
        assert c.post('/v1/runs/'+r['id']+'/reviews',json={'reviewer':'local','decision':'engineering_verified'}).status_code==201
        p=c.post('/v1/runs/'+r['id']+'/packages',json={}).json()
        assert c.post('/v1/packages/'+p['id']+'/receive',json={'receiver':'research','decision':'followup','reason':'try independent data'}).status_code==200
        html=c.get('/').text
        assert 'quant' in html and 'mandate-form' in html and 'delivery-form' in html


def test_bad_columns_and_small_samples(tmp_path):
    m=dataset(tmp_path)
    cfg=payload(m); cfg['features']=['missing']
    with pytest.raises(ValueError): execute_quant(cfg)
    cfg=payload(m); cfg['min_train']=80
    with pytest.raises(ValueError,match='12 out-of-sample'): execute_quant(cfg)
    cfg=payload(m); cfg['ridge']=float('nan')
    with pytest.raises(ValueError): execute_quant(cfg)

def test_package_contains_rerunnable_dataset_and_checks_tampering(tmp_path):
    from agh_pod.workflow import IntegrityError
    m=dataset(tmp_path); pod=Pod(tmp_path/'pod')
    op=pod.create_opportunity('Quant','investment_research')
    s=pod.create_spec(op['id'],payload(m)); pod.approve(s['id']); r=pod.run_spec(s['id'])
    pod.review(r['id'],'local','engineering_verified'); package=pod.export_package(r['id'])
    from pathlib import Path
    p=Path(package['path'])
    replay=execute_quant({**payload(m),'dataset':str(p/'dataset-manifest.json')})
    assert replay['metrics']==r['result']['metrics']
    (p/'dataset.csv').write_text('changed')
    assert not pod.verify_package(p)['valid']
    with (tmp_path/'data.csv').open('a') as f: f.write('2099-01-01,1,2\n')
    with pytest.raises(IntegrityError): pod.export_package(r['id'])


def test_nonfinite_data_rejected(tmp_path):
    m=dataset(tmp_path); p=tmp_path/'data.csv'; df=pd.read_csv(p)
    df['x']=df['x'].astype(float); df.loc[5,'x']=np.inf; df.to_csv(p,index=False)
    with pytest.raises(ValueError,match='finite'): execute_quant(payload(m))


def test_cli_quant_task(tmp_path,capsys):
    from agh_pod.cli import main
    m=dataset(tmp_path)
    task={'title':'CLI quant','mandate':{'objective':'forecast','baseline':'mean and persistence','acceptance':'report errors','stop_condition':'one run','receiver':'research'},'experiment':payload(m)}
    p=tmp_path/'task.json'; p.write_text(json.dumps(task))
    assert main(['--root',str(tmp_path/'cli'),'quant-run',str(p)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='succeeded'
