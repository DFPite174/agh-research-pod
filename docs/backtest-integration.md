# 指定 NautilusTrader 后端与接入资格（0.3.0）

当前账户后端为 https://github.com/DFPite174/ashare-nautilus-backtest-engine ，锁定 `b8d424df1a7c7c65b29eaab1be667a5368c8be5c` 与NT1.231.0。新研究入口优先且默认只调用此后端，不在Pod另造撮合，也不静默用其他库代替账户结果。

`run_equity_backtest` 新增EQUITY协议，支持受限历史表达式，通过独立Python进程调用公共run_backtest。版本与已跟踪文件检查在worker内完成；记录引擎Python和NumPy/pandas/Pydantic版本。候选与基线使用相同数据、资金、股数、参与率和原生费用。

0.3已实际验证：普通股票合成成交/30日对账，以及两个AStockDB主板日频窗口的受控模型规划、候选与基线账户回测、固定检验和研究包。原生资金/持仓对账与全部NAV日期必须通过，才能评价表现。结果见reports/ai-research-validation.json。

可转债接口保留为独立CONVERTIBLE_BOND请求，不伪装股票。新锁定版本的公共CB入口实际探测返回EXECUTED_NOT_QUALIFIED，见reports/nautilus-engine-probe-030.json；此探测无策略交易，不能据此宣称CB费用、T+0、条款现金流或论文空头腿完整验收。

历史reports/nautilus-engine-probe.json针对旧e231d8f版本，曾返回BLOCKED_ENGINE_CAPABILITY。该结论是历史诊断，不能套用成新版本公共入口仍拒绝CB。

## 配置

- AGH_BACKTEST_ENGINE_ROOT：本机指定仓库的干净checkout，提交必须匹配锁。
- AGH_ENGINE_PYTHON：独立安装NT1.231.0及引擎依赖的Python。
- AGH_GIT：可选Git可执行路径；未设时使用PATH。
- `agh engine-probe --engine-root ENGINE --python PYTHON` 探测现有CB路径。
- `agh research-start TASK.json --engine-root ENGINE --engine-python PYTHON` 执行新普通股票研究。

## 边界

信号只读取已结束Bar，在下一Bar执行。账户为现金多头，按原始价格成交，历史规则、股数单位、日历与公司行为必须明确输入。自动AStockDB导出尚未取得公司行为事件表，数据资格明确未认证。横截面、空头、衍生品和复杂生成代码超出本轮入口时应阻塞，不能声称已支持。

引擎是Bar级成交近似，不复原真实队列、盘口或集合竞价。每日账本对账只证明该模型下的账户一致，不证明现实成交或盈利。论文无成本多空统计、研究预测指标和账户结果继续分开。

本轮没有修改或推送指定引擎仓库；只使用并核验它的公开提交。
