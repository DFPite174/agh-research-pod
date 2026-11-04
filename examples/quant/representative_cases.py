"""Fixed multi-case acceptance suite. Run from repo root; download once, then cache."""
import hashlib
import html
import json
from pathlib import Path
import re
import time
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import statsmodels.api as sm

from agh_pod.quant import execute_quant
from agh_pod.workflow import Pod


URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip'
ROOT = Path('runtime/representative-cases')


def french_data(raw):
    """Only monthly six-digit records; do not mix annual observations or percentages."""
    rows = []
    for line in raw.decode('utf-8-sig').splitlines():
        if re.match(r'^\d{6},', line.strip()):
            parts = line.strip().split(',')
            rows.append([parts[0], *[float(v)/100 for v in parts[1:5]]])
    frame = pd.DataFrame(rows, columns=['date', 'market', 'size', 'value', 'rf'])
    frame['date'] = pd.to_datetime(frame.date, format='%Y%m') + pd.offsets.MonthEnd(0)
    # Fixed historical window; newest data are deliberately not used to choose dates.
    frame = frame[(frame.date >= '1960-01-01') & (frame.date <= '2024-12-31')].copy()
    if len(frame) != 780 or not np.isfinite(frame.iloc[:, 1:].to_numpy()).all():
        raise ValueError('expected complete 1960-2024 monthly factor observations')
    if (frame.iloc[:, 1:] <= -0.99).any().any():
        raise ValueError('factor missing sentinel or invalid return')
    frame['market_12m'] = frame.market.rolling(12).sum()
    frame['squared_return'] = frame.market**2
    frame['variance_12m'] = frame.squared_return.rolling(12).mean()
    return frame.dropna().reset_index(drop=True)


def improvement(records):
    actual = np.array([r['actual'] for r in records])
    error = np.mean((actual - [r['forecast'] for r in records])**2)
    mean = np.mean((actual - [r['baseline'] for r in records])**2)
    persistence = np.mean((actual - [r['persistence'] for r in records])**2)
    return {'vs_mean': float(1-error/mean) if mean else None,
            'vs_persistence': float(1-error/persistence) if persistence else None,
            'vs_stronger': float(1-error/min(mean, persistence)) if min(mean, persistence) else None}


def run_case(pod, name, frame, target, features, train, source, source_bytes, synthetic=False):
    folder = ROOT / name
    folder.mkdir(parents=True, exist_ok=True)
    frame.to_csv(folder/'data.csv', index=False)
    limitation = ('Generated control; no market evidence.' if synthetic else
                  'Revised historical snapshot; publication delays and vintage availability not modeled. No tradability or A-share inference.')
    manifest = {'csv': 'data.csv', 'source': source,
                'license': 'Generated fixture' if synthetic else 'Research use; source terms apply; raw data not committed',
                'evidence_level': 'synthetic' if synthetic else 'alternative_real', 'limitations': limitation}
    if not synthetic:
        manifest['frequency'] = 'quarterly' if 'statsmodels' in source else 'monthly'
    (folder/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    mandate = {'objective': name, 'baseline': 'Expanding mean and last observation',
               'acceptance': 'Compare fixed OOS errors against both baselines, report negative and split-sample findings',
               'stop_condition': 'One fixed ridge=1 experiment; no tuning', 'receiver': 'Local quant validation'}
    config = {'recipe': 'quant', 'dataset': str((folder/'manifest.json').resolve()),
              'target': target, 'features': features, 'min_train': train, 'ridge': 1.0}
    op = pod.create_opportunity(name, 'investment_research', name)
    pod.set_mandate(op['id'], mandate)
    artifact = pod.add_artifact('manual', name+' source snapshot', source_bytes, {'source': source})
    pod.link_artifact(op['id'], artifact['id'])
    spec = pod.create_spec(op['id'], config)
    pod.approve(spec['id'])
    started = time.perf_counter()
    run = pod.run_spec(spec['id'])
    if run['status'] != 'succeeded':
        raise RuntimeError(run)
    pod.review(run['id'], 'Local engineering acceptance', 'engineering_verified')
    package = pod.export_package(run['id'])
    assert pod.verify_package(package['path'])['valid']
    replay = execute_quant({**config, 'dataset': str(Path(package['path'])/'dataset-manifest.json')})
    assert replay['predictions'] == run['result']['predictions']
    records = run['result']['predictions']
    splits = [improvement(part) for part in (records[:len(records)//2], records[len(records)//2:])]
    full = improvement(records)
    if synthetic:
        verdict = '仅工程对照'
    elif full['vs_stronger'] <= 0:
        verdict = '未优于强基线'
    elif any(s['vs_stronger'] <= 0 for s in splits):
        verdict = '全期改善，分期不稳定'
    else:
        verdict = '全期及两分期均改善'
    pod.receive_package(package['id'], 'Local quant validation', 'followup',
                        'Local engineering signoff only; retain negative findings and independently qualify research data.')
    return {'name': name, 'evidence': manifest['evidence_level'], 'source': source,
            'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'start': str(frame.date.iloc[0])[:10], 'end': str(frame.date.iloc[-1])[:10],
            'oos_start': records[0]['date'][:10], 'oos_end': records[-1]['date'][:10],
            'rows': len(frame), 'features': features, 'min_train': train,
            'metrics': run['result']['metrics'], 'improvement': full, 'halves': splits,
            'verdict': verdict, 'workflow': 'PASS', 'package_replay': 'PASS',
            'seconds': round(time.perf_counter()-started, 3), 'run_id': run['id'],
            'package_id': package['id'], 'dataset_snapshot': run['result']['data_snapshot']}


def write_report(results, source_header):
    labels = {'inflation': '通胀预测', 'unemployment': '失业率预测', 'gdp_growth': 'GDP增长预测',
              'short_rate': '短端利率预测', 'market_return': '市场超额收益预测', 'size_factor': '规模因子预测',
              'value_factor': '价值因子预测', 'volatility_proxy': '平方收益波动代理',
              'iid_control': '独立噪声负对照', 'ar_control': 'AR(1)可预测对照'}
    lines = ['# AGH 代表性量化案例验证报告', '',
             '日期：2026-11-04。固定实验、保留负面结果；不把工程通过等同于投资有效。', '',
             '| 案例 | 数据期间 | 样本外数 | 对均值改善 | 对上一期改善 | 对较强基线改善 | 前/后半期对强基线 | 结论 | 闭环/重跑 |',
             '|---|---|---:|---:|---:|---:|---|---|---|']
    for r in results:
        f = lambda x: f'{x*100:+.2f}%'
        lines.append('| '+ ' | '.join([labels[r['name']], r['start']+'～'+r['end'], str(r['metrics']['n_oos']),
                     f(r['improvement']['vs_mean']), f(r['improvement']['vs_persistence']), f(r['improvement']['vs_stronger']),
                     '/'.join(f(h['vs_stronger']) for h in r['halves']), r['verdict'], '通过/一致'])+' |')
    lines += ['', '## 读表方法', '',
              '改善 = 1 − 模型MSE / 基线MSE；正数更好、负数更差。强基线取相同评价区间内两种基线中误差较低者，仅用于事后比较，不用于挑选交易信号。前后半期按该案例样本外记录等分，不是新的调参窗口。', '',
              '全部案例固定扩展窗口ridge=1；所有特征滞后一个观测，标准化只使用训练窗。宏观训练60期、月度因子训练240期、合成对照训练120期。没有调参或按结果删案例。', '',
              '## 数据与解释边界', '',
              '- 宏观：statsmodels随附FRED/BLS数据，1959–2009修订历史快照；GDP为实际GDP对数差乘100，非年化。删除首行初始化值。',
              '- 因子：[Kenneth French官方数据](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)，下载源：'+URL+'。源文件头：'+source_header.strip(),
              '- 因子原值由百分数转为小数。固定1960–2024窗口，12个月滚动特征形成后从1960-12开始；2025以后不参与实验。规模/价值是研究因子组合，不代表账户可直接执行。',
              '- 波动案例目标是月度市场超额收益平方，是波动代理而非日内已实现波动率；预测没有非负约束，不能直接作为风控生产估计。',
              '- 两个合成对照仅检查方法逻辑；固定种子下的负对照不保证每次一定不如基线。',
              '- 所有真实数据均未建立严格历史时点(PIT)资格；没有交易成本、融资借券、交易约束或账户回测。不报告收益率、夏普或盈利结论。',
              '- 这些案例验证同一受审查时序配方跨任务迁移，不能证明任意论文、横截面选股、组合优化或生成代码均可自动完成。',
              '- 每例完成来源归档、任务书、审批、运行、工程复核、交付、校验、包数据重跑和followup反馈；接收者为本地声明，非外部研究员签收。', '',
              '## 重跑', '', '`python examples/quant/representative_cases.py`。首次下载官方因子压缩包，后续使用runtime缓存。原始数据、任务状态和数据包不提交Git；报告JSON记录来源哈希、数据哈希、指标和任务ID。']
    Path('reports/representative-cases.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    headers = ['案例','样本外数','对均值改善','对上一期改善','对强基线改善','分期稳定性','闭环/重跑']
    rows = []
    for r in results:
        vals = [labels[r['name']], str(r['metrics']['n_oos']), *[f'{100*r["improvement"][k]:+.2f}%' for k in ('vs_mean','vs_persistence','vs_stronger')], r['verdict'], '通过 / 一致']
        rows.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AGH量化案例验证</title><style>body{font:16px/1.7 system-ui;margin:40px;background:#f5f7fa;color:#172535}table{border-collapse:collapse;background:white;width:100%}th,td{padding:13px;text-align:left;border-bottom:1px solid #dde4ec}th{background:#153449;color:white}p{max-width:1100px}.cards{display:flex;gap:20px;margin:25px 0}.cards div{padding:20px;background:white;border-radius:10px}h1{font-size:30px}</style><h1>AGH · 代表性量化案例验证</h1><p>2026-11-04｜固定参数，保留失败和负面结果。工程闭环通过，不代表投资有效。</p><div class="cards"><div>8 项真实数据案例</div><div>2 项合成逻辑对照</div><div>10/10 交付包重跑一致</div></div><table><tr>'+''.join('<th>'+v+'</th>' for v in headers)+'</tr>'+''.join(rows)+'</table><p>正数表示MSE降低，负数表示误差增加。强基线为历史均值和上一期数值中误差较低者。分期为样本外前/后半期。</p><p>真实数据为修订历史快照；未建模发布延迟、交易成本和账户约束。收益因子预测不等于策略收益，平方收益仅为波动代理。合成对照只验证逻辑。</p><p>详细期间、来源、方法、限制及重跑命令见同目录 representative-cases.md；原始指标见 representative-cases.json。</p></html>'
    Path('reports/representative-cases.html').write_text(page, encoding='utf-8')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    archive = ROOT/'french-factors.zip'
    if not archive.exists():
        archive.write_bytes(urllib.request.urlopen(URL, timeout=30).read())
    with zipfile.ZipFile(archive) as z:
        raw = z.read('F-F_Research_Data_Factors.csv')
    factors = french_data(raw)
    macro = sm.datasets.macrodata.load_pandas().data
    dates = pd.PeriodIndex.from_fields(year=macro.year.astype(int), quarter=macro.quarter.astype(int), freq='Q').to_timestamp(how='end').normalize()
    data = pd.DataFrame({'date': dates, 'inflation': macro.infl, 'unemployment': macro.unemp,
                         'short_rate': macro.tbilrate, 'gdp_growth': np.log(macro.realgdp).diff()*100}).iloc[1:]
    pod = Pod(ROOT/'pod')
    results = []
    for name in ('inflation', 'unemployment', 'gdp_growth', 'short_rate'):
        results.append(run_case(pod, name, data, name, ['inflation','unemployment','short_rate','gdp_growth'], 60,
                                'statsmodels macrodata; FRED/BLS accessed 2009-12-15', data.to_csv(index=False).encode()))
    for name, target in [('market_return','market'),('size_factor','size'),('value_factor','value'),('volatility_proxy','squared_return')]:
        results.append(run_case(pod, name, factors, target, ['market','size','value','rf','market_12m','squared_return','variance_12m'], 240, URL, raw))
    for name, coefficient in [('iid_control',0.0), ('ar_control',0.8)]:
        rng = np.random.default_rng(20261104)
        noise = rng.normal(0, 0.01, 600)
        values = noise.copy()
        for t in range(1, len(values)):
            values[t] += coefficient*values[t-1]
        frame = pd.DataFrame({'date': pd.date_range('2000-01-01', periods=600, freq='B'), 'return': values})
        results.append(run_case(pod, name, frame, 'return', ['return'], 120,
                                'Generated Gaussian innovations; seed=20261104; AR coefficient='+str(coefficient), frame.to_csv(index=False).encode(), True))
    report = {'date': '2026-11-04', 'cases': results, 'source_header': raw.decode().splitlines()[0],
              'selection': 'All fixed cases retained; no tuning or claimed independent final holdout',
              'engineering_passed': len(results), 'independent_researcher_signoff': False}
    Path('reports/representative-cases.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    write_report(results, report['source_header'])
    print(json.dumps([{'case':r['name'],'n':r['metrics']['n_oos'],**r['improvement'],'verdict':r['verdict']} for r in results],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
