# 通用量化任务操作指南

## 能力范围

AGH 0.2 复用 A/G/H 证据采集、分析和审批体系，增加可配置的单序列量化预测实验及下游反馈。研究方向不绑定特定作者。宏观、收益、波动等数值序列可以使用同一配方；横截面选股、任意生成代码和账户回测需要各自审查过的配方，不能直接冒充支持。

## 数据合同

CSV 必须含严格递增、无重复的 `date` 列与配置的目标和特征列；最多5000行、30个特征、25MB，数值必须有限。不填补缺失值。目标可同时作为特征，因为系统统一将所有特征滞后一个观测。行频率由数据提供者确定，必须先处理缺期、公告延迟和修订时点。

manifest 示例：

```json
{"csv":"series.csv","source":"dataset and vintage identifier","license":"authorized use description","evidence_level":"alternative_real","limitations":"Revised snapshot; release lags not modeled"}
```

真实替代数据标记 `alternative_real`，模拟数据标记 `synthetic`。该标签是调用者声明，不是数据科学认证。

任务 JSON 示例（dataset 相对任务文件解析）：

```json
{
  "title":"Inflation one-quarter forecast",
  "mandate": {
    "objective":"Forecast next quarterly inflation",
    "baseline":"Expanding mean and last observed value",
    "acceptance":"Report OOS errors against both baselines; retain negative findings",
    "stop_condition":"One fixed experiment; no parameter search",
    "receiver":"Quant research"
  },
  "experiment": {
    "recipe":"quant", "dataset":"manifest.json",
    "target":"inflation", "features":["inflation","unemployment","tbill"],
    "min_train":60, "ridge":1.0
  }
}
```

## 方法和评价

每个待预测观测 t 使用 t-1 行特征；训练仅使用此前已观测目标。均值与方差仅从当次训练窗口估计。使用有截距的 ridge 回归，截距不惩罚。最少12个样本外预测，min_train在12至2000之间。固定参数而非搜索后挑选最优结果。

输出每期实际值、预测、历史均值基线、上一期数值基线和训练样本数。`oos_r2` 相对历史均值，`r2_vs_persistence` 相对上一期数值；负值表示不如基线。预测误差改善不等于投资收益。

批准绑定来源证据、任务书快照、manifest和CSV哈希；更换数据必须创建并批准新规格。运行、复核、交付分开；任务书修改不回写既有规格。交付包内含CSV、原始及可重跑manifest和来源字节，方便移机重跑；需有对应数据分发授权，私有数据包不要提交Git。

## 接收反馈

包经校验后可记录 accepted/rejected/followup。反馈存入同一Pod并更新机会状态；不会改写已冻结交付包。此处身份是单用户本地声明，不是外部接收方签名。新增反馈需要随下游系统同步时，可读取 `agh list delivery`。

## 重跑

执行 `python examples/quant/validate.py` 离线生成真实宏观数据实验和合成收益检查，结果写入 `runtime/quant-validation`，摘要写入 `reports/general-quant-validation.json`。包中 `dataset-manifest.json` 的CSV路径已改为相对路径；将原spec的dataset改指该文件即可重跑，指标应相同，原规格和原审批记录保留不改。

## 未验证边界

没有新增模型凭据，未宣称在线模型完成任务规划；不执行下载的仓库或模型生成代码。真实宏观数据非严格PIT，未运行真实市场收益回测，未改变指定NautilusTrader后端。原可转债案例的数据与引擎限制仍按原验收记录保留。
