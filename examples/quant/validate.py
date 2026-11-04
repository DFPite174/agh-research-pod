"""Reproduce two fixed quantitative research tasks with bundled real macro data.
Run from repository root: python examples/quant/validate.py
No network, credential or external code execution is required.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels
import statsmodels.api as sm
from agh_pod.workflow import Pod


def main():
    root=Path('runtime/quant-validation').resolve(); root.mkdir(parents=True,exist_ok=True)
    frame=sm.datasets.macrodata.load_pandas().data
    dates=pd.PeriodIndex.from_fields(year=frame.year.astype(int),quarter=frame.quarter.astype(int),freq='Q').to_timestamp(how='end').normalize()
    data=pd.DataFrame({'date':dates,'inflation':frame.infl,'unemployment':frame.unemp,'tbill':frame.tbilrate})
    # The bundled first inflation observation is an initialization value, not measured growth.
    data=data.iloc[1:]; data.to_csv(root/'macro.csv',index=False)
    manifest={'csv':'macro.csv','source':'statsmodels '+statsmodels.__version__+' macrodata; FRED/BLS, accessed 2009-12-15',
              'license':'Public macroeconomic series distributed in statsmodels; verify source terms before redistribution',
              'evidence_level':'alternative_real','limitations':'Revised historical quarterly snapshot 1959Q2-2009Q3; release lags not modeled; no strict PIT or A-share performance evidence.'}
    (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    pod=Pod(root/'pod'); summary=[]
    for target in ('inflation','unemployment'):
        mandate={'objective':'One-quarter-ahead '+target+' forecast', 'baseline':'Expanding historical mean and last observed value',
                 'acceptance':'Report OOS MSE and R2, retain negative results; no parameter selection',
                 'stop_condition':'One fixed ridge=1 experiment with min_train=60; stop after delivery', 'receiver':'Quant method research'}
        task={'title':'Macro forecasting: '+target,'mandate':mandate,'experiment':{'recipe':'quant','dataset':'manifest.json','target':target,'features':['inflation','unemployment','tbill'],'min_train':60,'ridge':1.0}}
        (root/(target+'-task.json')).write_text(json.dumps(task,indent=2),encoding='utf-8')
        op=pod.create_opportunity(task['title'],'investment_research',mandate['objective']); pod.set_mandate(op['id'],mandate)
        source=pod.add_artifact('manual',task['title'],json.dumps(task).encode(),{'source':'fixed validation task','dataset_source':manifest['source']}); pod.link_artifact(op['id'],source['id'])
        payload={**task['experiment'],'dataset':str(root/'manifest.json')}
        spec=pod.create_spec(op['id'],payload); pod.approve(spec['id']); run=pod.run_spec(spec['id'])
        assert run['status']=='succeeded',run
        pod.review(run['id'],'Local engineering and temporal-integrity checks','engineering_verified')
        package=pod.export_package(run['id']); assert pod.verify_package(package['path'])['valid']
        feedback=pod.receive_package(package['id'],'Quant method research','followup','Method workflow validated; independently validate data vintage and market relevance before investment use.')
        summary.append({'target':target,'metrics':run['result']['metrics'],'sample_start':str(dates[1].date()),'sample_end':str(dates[-1].date()),'evidence_level':run['evidence_level'],'data_snapshot':run['result']['data_snapshot'],'run_id':run['id'],'package_id':package['id'],'delivery_decision':feedback['decision'],'predictions':run['result']['predictions']})
    rng=np.random.default_rng(7); returns=rng.normal(0,0.01,180)
    pd.DataFrame({'date':pd.date_range('2020-01-01',periods=180,freq='B'),'return':returns}).to_csv(root/'returns.csv',index=False)
    synthetic={**manifest,'csv':'returns.csv','source':'NumPy default_rng seed 7','license':'Generated fixture','evidence_level':'synthetic','limitations':'Independent Gaussian simulated returns; engineering logic only.'}
    (root/'synthetic.json').write_text(json.dumps(synthetic),encoding='utf-8')
    from agh_pod.quant import execute_quant
    simulated=execute_quant({'recipe':'quant','dataset':str(root/'synthetic.json'),'target':'return','features':['return'],'min_train':60,'ridge':1.0})
    report={'baseline_commit':'261a700','method':'Fixed expanding ridge=1; all inputs lagged one row; no tuning','real_cases':summary,'synthetic_case':{'metrics':simulated['metrics'],'research_status':simulated['research_status']},'limitations':manifest['limitations'],'source_documentation':'https://www.statsmodels.org/stable/datasets/generated/macrodata.html','independent_researcher_review':False}
    Path('reports/general-quant-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in case.items() if k not in {'predictions'}} for case in summary],indent=2))


if __name__=='__main__':
    main()
