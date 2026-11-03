# 指定 NautilusTrader 后端与接入资格

用户指定的账户回测后端为 [ashare-nautilus-backtest-engine](https://github.com/DFPite174/ashare-nautilus-backtest-engine)，本次锁定提交 `e231d8fb15ad67e4ff9f3525a53376c3cd49db34`，NT1.231.0，MIT。不在 ResearchPod 内另造交易撮合引擎。

适配器 `agh_pod.backends.nautilus` 通过独立 Python 进程读取并调用指定公共入口，核验 Git 提交与已跟踪文件未改动。依赖环境可与研究工作台分开，避免 Windows/Python3.12/Cython ABI 约束污染其他环境。只接受明确的 CONVERTIBLE_BOND 请求，不将债券改名为股票以绕过资产检查。

```powershell
agh engine-probe --engine-root LOCAL_ENGINE_CHECKOUT --python ENGINE_PYTHON
```

也可使用环境引用 `AGH_BACKTEST_ENGINE_ROOT`、`AGH_ENGINE_PYTHON`。这些值只在用户本机配置，仓库不固定用户目录。

## 本次实际探测

`reports/nautilus-engine-probe.json` 是实际版本和实际 NT1.231.0 调用结果。返回 `BLOCKED_ENGINE_CAPABILITY`，原因为公共入口拒绝可转债：`Only Shanghai/Shenzhen cash equities are supported`。

README 与独立组件宣称的 CB 支持不能代替公共回测验收。当前 CB 合同与费用测试通过，但 `engine/backtest.py` 的资产/报价准入、native Equity 构造、两位小数格式化、默认股票费用与独立费用核验仍未贯通 CB。网关和账本仍按 T+1，缺债券票息、到期/赎回注销、转股关联持仓事件；CASH/NETTING 账户与可卖库存约束不支持论文空头腿。

## 准入条件

正式可转债账户回测需要后端同时通过：

1. CONVERTIBLE_BOND 原生资产准入、0.001报价完整保留、10张数量单位。
2. 逐资产T+0与真实历史交易状态/价格边界，不能只修改证券类默认值。
3. CB费用接入原生撮合与独立参考账本，逐日现金/持仓/NAV对账。
4. 票息、到期/强赎/回售支付、债券注销、转股持仓变更的可核对事件协议。
5. 多空论文统计与现金多头账户结果分开；没有借券、融资和风险限制时，不称多空组合已执行。
6. 原始数据包含规则和事件，零量占位不被解释为可成交Bar。

本项目没有推送修改到回测引擎仓库；后端当前限制明确留在验收中。后端更新后须重新锁定版本、重跑能力与账户测试，再允许研究结果升级。

## 论文与账户评价的关系

论文五分组低减高收益属于无成本横截面研究统计，可以由 `empirical` 计算，不能被称为 NT账户模拟。正式资金回测只能走上述后端适配器，当前返回的阻塞状态不会生成NAV或伪造订单。`EXECUTED_NOT_QUALIFIED` 也只说明后端完成一次运行，不证明事件、费用、可交易性或论文已复现。
