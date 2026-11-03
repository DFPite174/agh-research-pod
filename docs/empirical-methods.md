# 实证计算契约与方法边界

`agh_pod.empirical` 是月度研究计算模块。所有收益、误定价、回归系数以十进制保存，例如 `0.012` 表示 1.2%；报告层自行转换。测试全部使用合成数据和独立手算/统计包参照，不能作为论文复现或市场收益证据。

## 输入与时点

`mispricing(market, model)` 返回 `(market-model)/model`。两类价格必须有限且严格大于零；标量返回 `float`，数组返回 NumPy 数组。除法分母为模型价格。

`form_portfolios(panel, weighting='equal', min_bonds=10, trim=0.05)` 接收 pandas DataFrame：

| 字段 | 约定 |
|---|---|
| date | 无时区、无日内时间的形成日期；每个月仅一个形成日期 |
| bond_id | 非空字符串；同日同券唯一 |
| market_price / model_price | 形成时市场/模型价格，均严格正值 |
| next_return | 调用者已经对齐的下一持有月简单总收益，包含适用的票息、赎回和终止事件；不得缺失，不能低于 -1 |
| risk_free | 同一个下一持有月的无风险收益，同月各券一致且大于 -1 |
| weight | 仅 `weighting='value'` 必需；形成时已知的有限正权重，组内归一化 |

模块不读取后续价格、不推算 `next_return`、不以零补终止收益，也不能仅凭这些列验证信息在形成时确实已知。实际数据的时点 (Point-in-Time)、总收益口径、复权、税费和交易约束必须由上游数据版本与 manifest 证明。没有 `next_return` 就报错。即使某券即将被价格剪尾或所属月份将被小样本排除，输入缺失/非有限仍然报错。

## 分组与记录

先校验整个输入，再逐形成月处理：

1. 检查剪尾前样本数。少于 `min_bonds` 的月份排除，并在 `result.attrs['excluded_months']` 记录日期、原始数量和原因；默认门槛是 10，不因剪尾后数量变化重查原门槛。
2. 以市场价格升序、`bond_id` 字典序排序，剪掉两端各 `floor(n*trim)` 条观测。此为确定性秩剪尾 (Rank Trimming)，避免百分位边界遇到价格并列而删除数量不定。10 券、5% 时每端剪掉 0 券，20 券时每端 1 券。剪尾后少于 5 券报错。
3. 按误定价升序，误定价相同则按 `bond_id` 字典序分开；用 NumPy `array_split` 分五组，余数从低误定价组起依次各多分一券。例如 18 券分 4/4/4/3/3。排序完全不使用下一月收益。
4. 组收益为等权平均；显式选择 `value` 后使用给定权重的组内加权平均。权重绝不从未来价格或下一期市值构造。

输出 DataFrame 每行对应一个**形成月**：`date`、`q1_return` 至 `q5_return`、`q1_excess` 至 `q5_excess`、`low_minus_high`、`market_excess`、`n_input`、`n_bonds`、`n_trimmed`、`tie_count`。`tie_count` 是剪尾后处于误定价并列组中的券数；并列不是统计上自然分界。`attrs['membership']` 保存每券分组，其他 attrs 保存剪尾、并列、收益时点和市场组合约定。CSV 默认不保存 attrs，报告/证据层应另存这些审计字段。

`qj_excess = qj_return - risk_free` 是单边持仓的超额收益。`low_minus_high = q1_return - q5_return` 是零投资多空差，**不再减无风险收益**。因各组使用同月无风险收益，它也等于 `q1_excess - q5_excess`。

`market_excess` 为该月通过输入校验的完整券集合（剪尾前）的等权平均下一期收益减同月无风险收益；小样本月不生成收益。它只是此输入宇宙的研究代理，不能冒充外部全市场指数。调用者也可单独提供论文指定的市场因子，必须登记其来源与定义。

以上剪尾整取、并列分配、余数处理和市场因子宇宙属于本实现公开的操作约定。论文描述不足以证明这些细节与作者原代码逐项一致；需要作者代码或附加方法证据才能消除差异。不同模型由调用者分别调用，模块不跨模型混合排序。

## 月度推断

`hac_mean(values: pd.Series, maxlags=3, confidence=0.95) -> dict` 要求带 `DatetimeIndex` 的连续月度序列，月份唯一且递增，数值有限。至少需要 `n > max(maxlags, parameter_count)` 个观测。不能用内连接或缺失值删除将不连续月份压缩为连续时间。排除过少券月份会造成自然缺月；应明确选取连续区间，或研究者另行审批支持日历间断的估计方法，不能静默压缩后运行这里的 HAC。

均值由常数项 OLS 估计；Newey–West 取 Bartlett 核、默认滞后 3，使用 `n/(n-k)` 有限样本协方差修正，t 检验/置信区间使用残差自由度的 Student-t 分布。这些推断约定明确记录在结果 `covariance` 字段；原文只披露 NW3，额外修正约定可能影响末位数值。返回 `estimate`、`standard_error`、`t_stat`、`p_value`、`confidence_interval`、`confidence`、`nobs`、`maxlags`、`inference_status`。零标准误等退化情形用 `DEGENERATE`、`t_stat=None`、`p_value=None`，不声称显著性。

`factor_alpha(returns: pd.Series, factors: pd.DataFrame, maxlags=3, confidence=0.95) -> dict` 估计 `return_t = alpha + beta' factor_t + error_t`，常数项和 NW3 约定同上。返回均值统计的通用字段（`estimate` 即 alpha），另加 `alpha`、`betas`、`r_squared`、`return_convention`。常数因子、秩亏、重复因子列或缺失值报错。两端日期必须完全相同，不排序拼接、不内连接；这也要求调用者将下一持有月因子明确对齐到形成月输出的日期标签，或将组合/因子同时改为持有月标签。这里不自动做月份移位。

传入单边组合时，`returns` 应已经是相应超额收益；传入低减高时应是零投资收益。函数本身不减无风险收益。多个因子模型由调用者分别调用，不因为样本缺失偷偷改变月度样本。

`fama_macbeth(panel, dependent, regressors, date_col='date', maxlags=3, confidence=0.95) -> dict` 要求列 `date_col`、`bond_id`、因变量和解释变量；月内债券标识唯一。每月对截面运行带常数 OLS，截面观测数必须大于参数数且设计矩阵满秩；然后对每个系数时间序列调用同一 NW3 均值估计。输出 `coefficients`（每项是完整 HAC 字典）、`monthly_coefficients`（日期索引 DataFrame，含每月 `nobs`）和 `n_months`。未声明截面权重或自发标准化/去极值，不能把这种通用计算直接视为论文某一张回归表的全规格实现。

## 目标对照与表 1 辅助

`compare_targets(targets: Mapping, observed: Mapping | None=None, *, atol=1e-8, rtol=0.0) -> DataFrame`：键为目标标识，值为数字，或含 `value` 的字典。目标字典还可含逐目标 `atol`/`rtol`。观测字典可含 `status='BLOCKED'/'NOT_RUN'` 与 `reason`；这两种状态保留且测量值清空。没有观测或观测为 NaN 时为 `NOT_RUN`，不复制论文数值补齐。有限实测值按 `abs(observed-expected) <= atol + rtol*abs(expected)` 判定 `PASS`/`FAIL`。输出 `target/expected/observed/error/atol/rtol/status/reason`。默认容差只用于算术测试；正式论文目标容差应按披露舍入精度、数据差异和预定规则单独设定。`PASS` 表示此项数值满足容差，不能替代真实数据、完整目标覆盖或独立复跑门禁。

`table1_statistics(values: pd.DataFrame) -> DataFrame` 将每个模型列汇总为 nobs、均值、样本标准差（ddof=1）、最小值、25%/中位数/75%分位数和最大值；不改变单位、不删除缺失、不默认为模型列建立不同样本。其输入可以是价格或误定价，调用者必须明确标记该表统计的量。至少两行、唯一模型列、全部数值有限。

## 已验证与未验证

测试验证已知分组手算、风险无重复扣减、价格尾部删除、并列稳定性、预对齐收益必需、缺失终止收益报错、少券月审计、权重约束、月度缺口、因子日期差异、秩亏和目标缺失状态；OLS/HAC 系数、标准误及检验对照独立 statsmodels 调用。数学/软件验证不包含 Wind/CSMAR 真实历史数据、商业许可核验、作者原代码、真实论文目标实测、容量或交易可执行性。
