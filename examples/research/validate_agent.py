"""Controlled model protocol + actual selected NT engine. No real model call.
Run with --engine-root, --engine-python; optional --astock-root adds real A-share cases.
"""
import argparse
import json
import os
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from agh_pod.equity_data import prepare_astock_dataset
from agh_pod.research_agent import create_research,run_research,export_research
from agh_pod.workflow import Pod


def synthetic_dataset(directory):
    directory.mkdir(parents=True,exist_ok=True)
    dates=pd.bdate_range('2024-01-02',periods=120)
    close=np.round(10+np.arange(120)*.01+np.sin(np.arange(120)/5)*.5,2)
    rows=[{'symbol':'600000.SH','date':d.date().isoformat(),'open':float(c),'high':round(float(c)+.1,2),'low':round(float(c)-.1,2),'close':float(c),'volume':1000000} for d,c in zip(dates,close)]
    pd.DataFrame(rows).to_csv(directory/'bars.csv',index=False)
    pd.DataFrame([{'symbol':r['symbol'],'date':r['date'],'trade_status':'OPEN','limit_state':'BOUNDED','down_limit':1.,'up_limit':100.,'buy_min':100,'buy_step':100,'sell_min':100,'sell_step':100,'max_order':1000000} for r in rows]).to_csv(directory/'rules.csv',index=False)
    pd.DataFrame({'date':[r['date'] for r in rows]}).to_csv(directory/'calendar.csv',index=False)
    m={'bars_csv':'bars.csv','rules_csv':'rules.csv','calendar_csv':'calendar.csv','source':'generated trend/sine engineering fixture','license':'generated','limitations':'Synthetic prices, weekday-only calendar and artificial price bands. No market evidence.','price_mode':'raw','volume_multiplier':1,'evidence_level':'synthetic','instruments':[{'symbol':'600000.SH','exchange':'SSE'}],'corporate_actions':[]}
    path=directory/'manifest.json';path.write_text(json.dumps(m),encoding='utf-8');return str(path)


def validate(args):
    root=Path('runtime/ai-research-validation').resolve();root.mkdir(parents=True,exist_ok=True)
    # Explicit fixture credentials scoped to this validation process, never a real secret.
    os.environ.update(AGH_LLM_API_KEY='controlled-response-fixture',AGH_LLM_MODEL='controlled-plan-fixture',AGH_LLM_BASE_URL='https://controlled.example/v1')
    pod=Pod(root/'pod')
    cases=[('synthetic',synthetic_dataset(root/'synthetic'))]
    if args.astock_root:
        for symbol in ('600519.SH','000001.SZ'):
            manifest=prepare_astock_dataset(args.astock_root,root/symbol,[symbol],'2023-01-01','2023-05-31')
            cases.append((symbol,manifest))
    summaries=[]
    for name,manifest in cases:
        source=pod.add_artifact('manual','Moving-average method definition',
            b'Engineering method fixture: buy after close exceeds its past 20-session average; sell below it. A 10-session variant is an explicitly labeled exploratory adaptation, not original-method replication.',
            {'kind':'method fixture, not a paper reproduction','author':'local validation'})
        seen=[]
        def respond(request):
            body=json.loads(request.content);prompt=json.loads(body['messages'][1]['content'])
            assert 'holdout' not in json.dumps(prompt['development_feedback'])
            seen.append(body)
            window=20 if len(seen)==1 else 10
            plan={'hypothesis':'Past moving-average timing may improve risk-adjusted exposure; test against equal-share buy-and-hold',
                  'evidence_ids':[source['id']],'assumptions':['raw-price technical signal','no standalone claim of PIT or corporate-event completeness'],
                  'adaptation':'Shanghai/Shenzhen cash long, historical closed bars, next-bar execution, fixed 100 shares',
                  'buy':f'close > sma(close, {window})','sell':f'close < sma(close, {window})',
                  'rationale':'Original 20-session rule' if window==20 else 'Explicit exploratory 10-session variant, registered as a new attempt',
                  'unsupported_reason':''}
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan)}}],'usage':{'total_tokens':600}})
        task=create_research(pod,{'title':'Controlled AI / native NT / '+name,'goal':'Validate the stated timing method in A shares; preserve negative findings',
                                 'artifact_ids':[source['id']],'dataset':manifest,'max_rounds':2,'initial_cash':1000000.,'holdout_sessions':20,'min_sessions':60})
        result=run_research(pod,task['id'],engine_root=args.engine_root,engine_python=args.engine_python,
                            client=httpx.Client(transport=httpx.MockTransport(respond)))
        assert result['status'] in {'COMPLETED_RESEARCH','COMPLETED_NEGATIVE'},result
        package=export_research(pod,task['id']);assert pod.verify_package(package['path'])['valid']
        attempts=[pod.get('research_attempt',i) for i in result['attempt_ids']]
        selected=pod.get('research_attempt',result['selected_attempt'])['evaluation']
        holdout=result['holdout']
        assert holdout['status'] in {'EVALUATED','NOT_RUN'}
        summary={'case':name,'model_evidence':'CONTROLLED_RESPONSE_NOT_LIVE_MODEL','engine_evidence':'ACTUAL_NATIVE_NAUTILUS_1.231.0',
                 'task_id':task['id'],'package_id':package['id'],'status':result['status'],'rounds':len(attempts),
                 'calls':result['calls'],'reserved_tokens':result['reserved_tokens'],'reported_tokens_known':result['reported_tokens_known'],
                 'selected_attempt':result['selected_attempt'],'selected_rules':pod.get('research_attempt',result['selected_attempt'])['plan'],
                 'development':{k:selected[k] for k in ('excess_return','meets_fixed_thresholds','sample_adequate')},
                 'development_metrics':{k:v['metrics'] for k,v in selected['runs'].items()},
                 'holdout':{k:holdout.get(k) for k in ('status','excess_return','meets_fixed_thresholds','sample_adequate')},
                 'holdout_metrics':{k:v['metrics'] for k,v in holdout.get('runs',{}).items()},
                 'holdout_used_once':result['holdout_used_once'],'package_verification':'PASS',
                 'data_snapshot':result['dataset_snapshot'],'engine_revision':result['engine_revision'],
                 'conclusion':'Exploratory protocol/account integration only; corporate events/PIT and real model competence unqualified'}
        summaries.append(summary)
    report={'version':'0.3.0','validation':'controlled model responses with actual specified account engine',
            'live_model':'NOT_RUN by user choice','arbitrary_python':'NOT_RUN; Docker daemon unavailable; bounded DSL only',
            'cases':summaries}
    Path('reports/ai-research-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for case in summaries:
        print(json.dumps({k:case[k] for k in ('case','status','rounds','development','holdout','package_verification')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-root',required=True);parser.add_argument('--engine-python',required=True)
    parser.add_argument('--astock-root')
    validate(parser.parse_args())
