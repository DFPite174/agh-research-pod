import json
from pathlib import Path
import pytest
from agh_pod.workflow import Pod, canonical, digest
from agh_pod.quant import execute_quant


def quant_case(tmp_path):
    import numpy as np
    import pandas as pd
    df=pd.DataFrame({'date':pd.date_range('2000-01-31',periods=72,freq='ME'),'x':np.sin(np.arange(72))})
    df.to_csv(tmp_path/'data.csv',index=False)
    m=tmp_path/'manifest.json'; m.write_text(json.dumps({'csv':'data.csv','source':'fixture','license':'generated','evidence_level':'synthetic','limitations':'engineering'}))
    cfg={'recipe':'quant','dataset':str(m),'target':'x','features':['x'],'min_train':24}
    pod=Pod(tmp_path/'pod'); op=pod.create_opportunity('test','investment_research')
    a=pod.add_artifact('manual','evidence',b'evidence'); pod.link_artifact(op['id'],a['id'])
    s=pod.create_spec(op['id'],cfg); pod.approve(s['id']); r=pod.run_spec(s['id']); pod.review(r['id'],'local','engineering_verified')
    return pod,op,r,cfg


def test_quant_package_cannot_omit_approved_attachments(tmp_path):
    pod,op,r,cfg=quant_case(tmp_path); p=Path(pod.export_package(r['id'])['path'])
    m=json.loads((p/'manifest.json').read_text()); m['files']={k:v for k,v in m['files'].items() if k in {'run.json','spec.json','opportunity.json','reviews.json'}}
    (p/'manifest.json').write_bytes(canonical(m))
    assert not pod.verify_package(p)['valid']


def test_quant_package_cannot_replace_dataset_and_rehash_manifest(tmp_path):
    pod,op,r,cfg=quant_case(tmp_path); p=Path(pod.export_package(r['id'])['path'])
    (p/'dataset.csv').write_text('date,x\n2000-01-01,999\n')
    m=json.loads((p/'manifest.json').read_text()); m['files']['dataset.csv']=digest((p/'dataset.csv').read_bytes()); (p/'manifest.json').write_bytes(canonical(m))
    assert not pod.verify_package(p)['valid']


def test_receive_feedback_rolls_back_if_opportunity_update_fails(tmp_path,monkeypatch):
    pod,op,r,cfg=quant_case(tmp_path); package=pod.export_package(r['id'])
    original=pod._save
    def fail(kind,body,**kwargs):
        if kind=='opportunity': raise RuntimeError('injected write failure')
        return original(kind,body,**kwargs)
    monkeypatch.setattr(pod,'_save',fail)
    with pytest.raises(RuntimeError): pod.receive_package(package['id'],'local','accepted','test')
    assert pod.list('delivery')==[]


def test_duplicate_csv_columns_rejected(tmp_path):
    pod,op,r,cfg=quant_case(tmp_path)
    p=tmp_path/'data.csv'; p.write_text(p.read_text().replace('date,x','date,x,x').replace('\n','\n',1))
    with pytest.raises(ValueError,match='column'): execute_quant(cfg)


def test_declared_monthly_gap_and_late_availability_rejected(tmp_path):
    import pandas as pd
    pod,op,r,cfg=quant_case(tmp_path); p=tmp_path/'data.csv'; m=tmp_path/'manifest.json'
    meta=json.loads(m.read_text()); meta['frequency']='monthly'; m.write_text(json.dumps(meta))
    df=pd.read_csv(p); df=df.drop(index=15); df.to_csv(p,index=False)
    with pytest.raises(ValueError,match='calendar'): execute_quant(cfg)
    df=pd.read_csv(p); df['available_at']='2099-01-01'; df.to_csv(p,index=False)
    meta.pop('frequency'); meta['availability_column']='available_at'; m.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='available'): execute_quant(cfg)

def test_receive_refuses_another_valid_export_in_same_directory(tmp_path):
    import shutil
    from agh_pod.workflow import IntegrityError
    pod,op,r,cfg=quant_case(tmp_path); first=pod.export_package(r['id']); second=pod.export_package(r['id'])
    for f in Path(second['path']).iterdir(): shutil.copyfile(f,Path(first['path'])/f.name)
    with pytest.raises(IntegrityError,match='recorded export'): pod.receive_package(first['id'],'local','accepted','wrong package')


def test_source_attachment_cannot_be_removed_from_package_manifest(tmp_path):
    pod,op,r,cfg=quant_case(tmp_path); p=Path(pod.export_package(r['id'])['path'])
    m=json.loads((p/'manifest.json').read_text()); m['files']={k:v for k,v in m['files'].items() if not k.startswith('evidence-')}; (p/'manifest.json').write_bytes(canonical(m))
    assert not pod.verify_package(p)['valid']


def test_analysis_is_persisted_with_input_hashes_and_not_run_status(tmp_path,monkeypatch):
    monkeypatch.delenv('AGH_LLM_API_KEY',raising=False); monkeypatch.delenv('AGH_LLM_MODEL',raising=False)
    pod=Pod(tmp_path); a=pod.add_artifact('manual','source',b'quant research')
    result=pod.analyze_artifacts([a['id']])
    assert result['status']=='NOT_RUN'
    stored=pod.get('analysis',result['id'])
    assert stored['evidence'][0]['sha256']==a['sha256']
    assert stored['budget']['max_total_tokens']==5000


def test_malformed_provider_container_is_a_failed_analysis(monkeypatch):
    import httpx
    from agh_pod.analyst import analyze
    monkeypatch.setenv('AGH_LLM_API_KEY','test'); monkeypatch.setenv('AGH_LLM_MODEL','test')
    result=analyze([{'id':'a','content':'test'}],client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=[]))))
    assert result['status']=='FAILED'


def test_dashboard_omits_bulk_predictions(tmp_path):
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    pod,op,r,cfg=quant_case(tmp_path)
    with TestClient(create_app(pod.root)) as c:
        html=c.get('/').text
        assert 'train_count' not in html
        assert c.get('/v1/runs/'+r['id']).json()['result']['predictions']


def test_invalid_package_json_returns_validation_failure(tmp_path):
    (tmp_path/'manifest.json').write_text('[]')
    assert not Pod.verify_package(tmp_path)['valid']

def test_analysis_api_persists_unconfigured_result(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    monkeypatch.delenv('AGH_LLM_API_KEY',raising=False); monkeypatch.delenv('AGH_LLM_MODEL',raising=False)
    app=create_app(tmp_path); a=app.state.pod.add_artifact('manual','source',b'evidence')
    with TestClient(app) as c:
        r=c.post('/v1/analyses',json={'artifact_ids':[a['id']]}).json()
        assert r['status']=='NOT_RUN'
        assert c.get('/v1/analyses').json()[0]['id']==r['id']


def test_local_service_rejects_foreign_host_and_origin(tmp_path):
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/v1/health',headers={'Host':'evil.example'}).status_code==400
        assert c.post('/v1/opportunities',json={'title':'external','research_type':'investment_research'},headers={'Origin':'https://evil.example'}).status_code==403
        assert c.get('/v1/opportunities').json()==[]


def test_bad_calendar_intraday_rejected(tmp_path):
    import pandas as pd
    pod,op,r,cfg=quant_case(tmp_path); p=tmp_path/'data.csv'; df=pd.read_csv(p)
    df['date']=pd.to_datetime(df.date)+pd.Timedelta(hours=12); df.to_csv(p,index=False)
    with pytest.raises(ValueError,match='calendar dates'): execute_quant(cfg)

@pytest.mark.parametrize('single_row',[False,True])
def test_csv_extra_fields_are_not_silently_discarded(tmp_path,single_row):
    pod,op,r,cfg=quant_case(tmp_path); p=tmp_path/'data.csv'; lines=p.read_text().splitlines()
    for i in range(1,2 if single_row else len(lines)): lines[i]+=',999'
    p.write_text('\n'.join(lines))
    with pytest.raises(ValueError,match='field count'): execute_quant(cfg)

@pytest.mark.parametrize('status',['FAILED','BLOCKED_INPUT'])
def test_cli_analysis_failure_has_nonzero_exit(tmp_path,monkeypatch,capsys,status):
    from agh_pod.cli import main
    monkeypatch.setattr(Pod,'analyze_artifacts',lambda *a,**kw:{'status':status,'analysis':None})
    assert main(['--root',str(tmp_path),'analyze','source'])==1
    assert json.loads(capsys.readouterr().out)['status']==status

def test_tushare_malformed_container_does_not_crash_probe(monkeypatch):
    import httpx
    from agh_pod.providers.tushare import probe_tushare
    monkeypatch.setenv('TUSHARE_TOKEN','test')
    result=probe_tushare(client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=[]))))
    assert result['status']=='QUALIFICATION_INCOMPLETE'
    assert all(p['outcome']=='ERROR' for p in result['probes'])


def test_pdf_text_budget_stops_before_extracting_more_pages(monkeypatch):
    import agh_pod.documents as documents
    class First:
        def extract_text(self): return 'a'*100
    class Second:
        def extract_text(self): pytest.fail('extracted a page after exceeding text budget')
    class Reader:
        is_encrypted=False
        pages=[First(),Second()]
    monkeypatch.setattr(documents,'PdfReader',lambda _:Reader())
    with pytest.raises(ValueError,match='character budget'): documents.prepare_evidence(b'%PDF-fake',max_characters=20)
