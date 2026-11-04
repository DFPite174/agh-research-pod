# AGH Research Pod：项目定义与详细说明（0.3.0）

更新：2026-11-04。本文件为当前产品定义，取代旧报告中以自动雷达和订阅为优先的建议。当前不要求无人触发的自动发现。

## 1. 产品定义

AGH Research Pod 是人工触发、AI驱动、面向A股的研究验证工作台。用户指定人物、文章、论文或项目及研究目标；指定模型通过API解构材料并提出可检验假设和候选实现；Pod在授权的数据和资源范围内准备数据、冻结规格，优先调用指定NautilusTrader引擎，执行固定检验和有预算的迭代，交付可复核的适用性结论。

产品交付的是证据、实验和结论，不保证研究对象有效，也不保证发现盈利策略。未优于基线、条件不适用、证据或数据不足，均是合格的研究产出。

A/G/H保留Academic、GitHub、Hugging Face来源含义，但不限制用户指定人物或手动材料。当前以用户明确提交的对象为入口，不建设无人值守资讯扫描。

## 2. 用户输入与授权

一次研究包含对象材料、具体问题、目标证券/数据窗口、固定资金与股数、基线和阈值、最大迭代轮数及模型token预算。来源可以手动导入PDF/文本，或通过既有连接器归档仓库README、论文元数据和模型卡。人物研究依赖所提供的可核实材料，不根据名字凭空推断完整投资体系。

手工触发授权Pod执行该范围内的受审查数据工具、受限策略表达式和固定引擎；不授权模型修改正式评估器、引擎版本、密钥、数据根目录或封存测试区。模型无法发起任意shell操作。数据窗口和股票名单在开始后不能随成绩偷偷变化。

## 3. 业务流程

用户指定对象与目标
→ 归档来源、检查材料可读性和数据条件
→ AI解构原主张、假设及A股适配
→ 冻结候选计划、策略代码和数据快照
→ 指定NautilusTrader引擎执行候选与基线
→ 固定程序检查账本、样本、成本、超额与回撤
→ 未达到条件时在预算内创建下一实验版本
→ 开发区达标后，选定候选进入一次最终保留区检验
→ 形成正面、负面或阻塞结论及研究证据包。

数据探测和标准化导出可以在AI规划前进行，以便给模型真实的数据能力边界。0.3的标准数据准备由受控工具根据用户允许的证券与窗口完成；模型编写策略表达式。尚不是模型自主编写任意ETL/Python并执行的通用Coding Agent。

## 4. 分工与架构

| 组件 | 职责 | 不具备的权限 |
|---|---|---|
| 用户 | 指定对象、范围、预算、阈值，接收结论 | 无需逐条批准常规计算 |
| 模型API | 阅读证据、生成假设/适配说明/候选表达式，依据开发区反馈提出修订 | 不能改引擎、验收器、保留区、密钥或路径 |
| Pod研究控制器 | 状态、预算预留、版本、哈希、任务执行和包导出 | 不把模型叙述当作实测数字 |
| 数据准备工具 | 本地库只读导出、字段映射、单位/规则/日历检查 | 不改源库、不补造价格或停牌 |
| 受限策略解释器 | 对已结束Bar的历史计算信号 | 不支持import、属性访问、文件/网络或eval/exec |
| 指定账户引擎 | 原生订单/成交/费用/持仓与独立账本对账 | 不代表实盘、真实盘口或未建模资产能力 |
| 固定评估器 | 工程完整性、样本与固定经济阈值、同条件基线 | AI候选无法修改 |
| 研究交付层 | 原材料、数据、策略、计划、所有轮次和结果包 | 校验通过不等于科学认证 |

0.3使用同一指定模型承担规划和候选修订，固定程序独立检验。另一个AI批评者可以后续增加，但不能替代账本和数值校验。当前没有宣称已经实现独立模型研究员复核。

## 5. 指定回测引擎优先

唯一默认账户回测后端是 https://github.com/DFPite174/ashare-nautilus-backtest-engine ，本轮锁定提交 `b8d424df1a7c7c65b29eaab1be667a5368c8be5c`，NautilusTrader为1.231.0。执行前检查Git版本及已跟踪文件是否干净，实际子进程记录Python/关键依赖版本。

账户型策略优先走其公共run_backtest接口；候选和基线使用相同数据、账户资金、固定股数、参与率、日历、规则及费用。只读取已结束Bar，意图最早在下一Bar开盘执行。模型无权把引擎能力缺口改写成“已通过”，也不会静默用pandas或其他引擎替换账户结果。

0.3研究入口接通沪深普通股票、现金多头、日频量价择时。既有可转债接口保留且更新版本锁，但可转债现金流、复杂条款和空头腿仍需独立验收，不能继承普通股票的通过状态。统计检验可作为辅助，但不替代可执行账户回测。

涉及做空、期权、跨资产或未支持组合方法时，返回BLOCKED_METHOD/引擎阻塞，记录缺口。未来如引入补充引擎，需要显式标注用途、结果层级和授权。

## 6. AI API和策略代码

使用兼容 `/chat/completions` 的接口，并要求服务支持本项目使用的JSON Schema结构化响应。模型可替换，不依赖特定品牌。环境变量为AGH_LLM_BASE_URL、AGH_LLM_MODEL、AGH_LLM_API_KEY；配置在启动Pod的同一进程环境，修改后重启服务，不在网页或聊天中提交密钥。

每轮模型返回hypothesis、evidence_ids、assumptions、adaptation、buy、sell、rationale、unsupported_reason。引用只能使用已提供证据ID；这检查引用归属，不证明论述被原文支持，仍需研究复核。

当前候选“代码”是可组合的历史表达式DSL，例如：

```text
buy: close > sma(close, 20) and ret(close, 5) > 0
sell: close < sma(close, 20)
```

支持open/high/low/close/volume、sma/std/lag/ret、四则运算、比较和and/or/not，窗口1至252。表达式节点/长度有预算，历史不足时不交易。源码作为策略证据归档，由可信解释器计算，不执行模型Python。

这覆盖部分量价择时方法；不覆盖任意论文算法、基本面数据处理、横截面模型训练或任意开源项目复刻。任意Python的隔离执行器尚未实现；本机Dockerdaemon也未运行。启动Docker不会自动令此能力获得验收。

## 7. 数据准备与资格

用户可以提供标准manifest，也可提交data_request（股票、开始、结束），由Pod只读导出AStockDB。优先使用已配置AGH_ASTOCKDB_ROOT，否则按本机约定目录自动寻找有效根目录；不要求用户重复确认既定路径。原项目DuckDB仍可用于原审计接口，但它只有约10个交易日，不能满足本轮长样本研究。

自动导出当前支持1至10只沪深主板证券，读取research_daily的原始OHLCV、历史边界与交易状态以及trading_calendar。数据库以read_only打开，外部文件访问只允许该根目录的data文件夹，以兼容其Parquet视图。输出写入Pod自己的运行目录，不修改源库。

原始成交价格与信号价格不混用；volume_multiplier明确为股或手。每日规则覆盖每个证券和交易日；缺行不推断为停牌，不填造价格。输入快照和实现模块哈希进入任务contract；任务触发后文件或实现变化须创建新任务。

当前自动导出未取得公司行为事件表，默认空事件并明确限制。因此真实数据案例仅证明价格/规则/账户集成，不是完整总回报或PIT认证。多字段发布时间、修订版本、历史股票池和公司行为仍需独立资格审查。提供完整manifest时可以显式附corporate_actions，具体事件能力由引擎验收。

## 8. 验收、保留区与迭代

工程检验：所选引擎实际完成、原生与参考现金一致、每日资金/持仓对账、NAV日期与冻结日历一致、结果数值有限且净值为正。工程失败不能解释为策略表现差。

默认开发区阈值：至少60个交易日、候选扣费账户收益严格超过同股数买入持有、最大回撤不超过30%、至少有一笔成交。阈值由用户任务冻结，模型不能修改。候选排序先比较是否满足全部阈值，再比较超额，不挑选回撤不合格但收益更高的候选。

默认最后20个交易日是任务内保留区。每轮只向模型反馈开发区指标；开发区未达标则COMPLETED_NEGATIVE，不使用保留区。达标后候选固定，仅检验一次，结果不再送模型调参。保留区开始时账户为空仓，历史Bar只用于预热信号，首次意图仍在下一Bar执行。保留区最少20期的检查仅是当前最小门槛，不是统计显著性保证。

模型最大轮数默认2、上限5；总token默认50000、上限200000，每次调用前按UTF-8输入与输出上限保守预留并持久记录。已知provider用量累计保存，缺失用量标unknown；报告超单次预留或总预算立即停止。成本以token控制，尚无供应商货币费用核对。

这些限制在单个任务内生效。新建任务可能重复使用相同历史区间，当前没有跨任务封存区访问治理和多重检验惩罚；用户不能把反复新建任务筛选后的结果称为独立样本外发现。

固定股数基线不等于满仓指数基线。例如100股茅台与100万元账户含大量闲置现金，账户收益不能直接当作股票收益或市场收益。报告保留资金、股数、费用和成交，避免误读。

## 9. 状态与交付

queued/running：已触发或处理中；stage显示reading/planning/backtesting。
COMPLETED_RESEARCH：流程完成，不代表策略有效；需检查开发/保留区各自结果。
COMPLETED_NEGATIVE：开发区未达到固定条件，保留区未使用。
NOT_RUN：未配置模型；BLOCKED_INPUT：扫描件等材料不可直接读取。
BLOCKED_METHOD：方法超出当前支持范围；BLOCKED_ENGINE_CONFIGURATION/BLOCKED_BACKTEST：引擎配置或能力阻塞。
BUDGET_EXHAUSTED/PROVIDER_BUDGET_OVERRUN：预留预算不足或提供方报告超额。
FAILED：数据/代码哈希变化、非法表达式、错误引用或其他可记录错误。

每轮hypothesis、适配、表达式、使用量、候选/基线原生结果及评价保存为research_attempt。研究包包含原始证据、原始与可移机重跑数据清单、CSV、冻结contract、各轮记录和策略源码。`agh package-verify`支持旧包及research-1新包，校验资料、哈希和关联。包本身不附数字签名，不能抵御数据库与全部证据同时被恶意改写。

## 10. 操作入口

CLI：`agh research-start TASK.json --engine-root ENGINE --engine-python PYTHON`；数据manifest相对TASK.json解析。`agh research-export TASK_ID`导出；`agh package-verify PACKAGE_DIRECTORY`校验；`agh list research`及`agh list research_attempt`查看。

HTTP：POST /v1/research人工触发，GET /v1/research列摘要，GET /v1/research/{id}查完整轮次和结果，POST /v1/research/{id}/export导出。网页新增AI驱动A股研究表单，使用本机配置的模型和引擎。

最小TASK示例：

```json
{
  "title":"指定文章的均线方法在A股是否有增量价值",
  "goal":"忠实记录原设定，检验扣费后相对同股数买入持有的表现；保留失败",
  "artifact_ids":["已导入材料的ID"],
  "data_request":{"symbols":["600519.SH"],"start":"2023-01-01","end":"2023-05-31"},
  "max_rounds":2,"max_total_tokens":50000,"max_output_tokens":1500,
  "shares":100,"initial_cash":1000000.0,"participation_rate":0.01,
  "holdout_sessions":20,"min_sessions":60,"min_excess_return":0.0,"max_drawdown":0.3
}
```

也可以用dataset字段替换data_request，提供含bars_csv、rules_csv、calendar_csv、instruments、price_mode=raw、volume_multiplier、source、license、limitations、evidence_level及可选corporate_actions的manifest。案例格式见examples/research/validate_agent.py。

## 11. 类似项目借鉴

| 项目 | 核实来源与可借鉴方法 | 本项目取舍 |
|---|---|---|
| Microsoft RD-Agent | https://github.com/microsoft/RD-Agent ：假设/研发/反馈循环及量化研究场景 | 借鉴版本化实验与反馈；不引入整个框架，不继承其效果声明 |
| Microsoft Qlib | https://github.com/microsoft/qlib ：研究工作流、实验记录及RD-Agent整合 | 借鉴数据/实验/评价分离；不替代用户指定账户引擎 |
| FinRobot | https://github.com/AI4Finance-Foundation/FinRobot ：模型推理与确定性金融计算分离 | 模型提案，程序计算与验证；不照搬其多智能体数量或生产声明 |
| Open Deep Research | https://github.com/langchain-ai/open_deep_research ：研究任务分工、结构化配置和计划/执行方法 | 借鉴上下文/计划分工；公开仓库已归档，仅作方法参考 |
| DeepSeek Super-Agent原型 | https://github.com/deepseek-ai/dsh-superagent-prototype ：授权任务、独立工作项、交付与少打扰 | 人工触发授权、持久任务、受控执行；不声称运行原版系统 |

以上为截至2026-11-04查阅官方README/仓库后的设计取舍，不证明竞品收益、生产成熟度或本项目已实现其全部能力。没有复制这些项目的代码或增加它们作为运行依赖。

## 12. 当前完成与后续边界

0.3已实现：手工触发、证据阅读与严格计划接口、受限策略代码生成、标准数据准备、固定引擎普通股票执行、基线/对账/样本检验、预算内迭代、开发/保留区分离、研究包与CLI/API/网页。

本轮用户选择稍后配置真实模型API，故模型协议使用受控响应验证；指定引擎是真实运行，不能把这两种证据混称为“真实AI端到端研究成功”。完整验收表与实际账户结果见reports/ai-research-validation.json和reports/ai-research-acceptance.md。

后续重点是：配置真实模型后对人物/文章/项目逐类验收；独立研究员核查忠实性；补齐公司行为/PIT与跨任务试验治理；增加横截面及基本面配方；实现经过验收的任意Python隔离执行；加强强制取消、进程租约和运营工具。当前没有全市场覆盖、任意论文一键复现、自动策略准入或实盘交易承诺。
