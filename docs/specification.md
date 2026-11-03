# AGH ResearchPod / 中国可转债定价模型比较研究

2026-11-03。用户已授权严格设计、实现、验证并同步到指定仓库。本规格将前一轮通用设计收敛为可运行首版：研究证据工作流、A/G/H接入、有限模型分析、可转债复现配方与可信评价。

## 冻结研究对象

郑振龙、竺添晟、陈蓉，经济学（季刊）2025年第1期，173–190，DOI10.13821/j.cnki.ceq.2025.01.11。正文物理页1–18，对应印刷173–190。正式公开全文 https://nsd.pku.edu.cn/docs/20250227142007660959.pdf 。附录以本次核实的期刊公开地址为准。原PDF和商业数据不提交到Git。

样本2000-07至2022-06，696只债、14,980个月末定价观测。排除可交换债和异常价格；250交易日正股波动率；国债即期曲线按剩余期限插值；信用利差1个月/1年/3年/5年分别0.0065/0.0072/0.0090/0.0098。TF/LYW/LW用200步三叉树，ZL用10,000条路径。原文并未给出全部代码/数据/条款历史。

核心研究目标：表1五模型描述性统计；图1–3定价/在值程度/期限关系；表2全样本及2018前后五分组超额收益与MKT alpha；表3五类因子alpha；正文稳健性与在线附录目标登记。原文mispricing=(market-model)/model，从低到高分组，低组减高组；月末形成，下一月收益；剔除当月券少于10的月份和价格两端5%；Newey-West滞后3。2018分界为2018-01。

## 工程契约

Python>=3.12，NumPy/SciPy/pandas/statsmodels计算，FastAPI+服务端本地工作台，SQLite与哈希文件证据库，CLI统一应用用例。避免为首版引入第二套UI运行时。默认127.0.0.1，单受信任用户；不声称多租户/公网安全。静态检查采用已验证的纯Python Pyflakes，依赖约束与锁定基线入库。

用户后续指定的数据绑定优先：使用其DuckDB数据湖只读适配器，覆盖其他默认数据库建议；账户回测仅接入DFPite174/ashare-nautilus-backtest-engine，当前锁定e231d8fb15ad67e4ff9f3525a53376c3cd49db34，NT1.231.0。真实库和后端资格诊断分别见reports。当前数据覆盖与引擎CB公共入口未通过，不以工程预览代替完整研究验收。

定价独立模块 `agh_pod.pricing`：dataclass Coupon(time,amount), Trigger(ratio,window,required,start,end,payment), BondContract(face,spot,conversion_price,maturity,risk_free,credit_spread,volatility,dividend_yield,coupons,call,put,reset_floor,history)。字段详解与JSON入口由模块维护。`price(contract,model,steps=200,paths=10000,seed=42)`返回JSON可序列化对象，包含price、standard_error、diagnostics、method_status。模型名BS/TF/LYW/LW/ZL。校验所有输入有限、正值与时间/条款有效性。

BS按论文式3：无风险贴现债券部分＋转换股数×股票的欧式看涨表示（到期赎回为执行价），包括票息。TF拆现金与股票流贴现；LYW/LW为论文代理条款边界，不把代理称作真实路径条款。ZL逐日模拟GBM、滚动触发、赎回优先、回售触发后通过BS反解下修、折现；下修约束、历史状态和未披露细节必须登记。所有模型最终报告原文不确定性，不默认精确复现。无条款、零信用利差的数值结果对照BS；到期/零波动/票息手算；ZL误差和种子重复性。

实证模块 `agh_pod.empirical`：`mispricing(market,model)`；`form_portfolios(panel,weighting='equal',min_bonds=10,trim=0.05)` 输入DataFrame(date,bond_id,market_price,model_price,next_return,risk_free[,weight])；严格按形成日期输出下一期组合收益，不自动伪造缺失终止收益。排序并列使用bond_id稳定打散并报告。收益单位十进制。`hac_mean`, `factor_alpha`, `fama_macbeth`, `compare_targets`提供样本数、估计、NW3、置信/误差规则。不得通过inner join静默漏掉缺因子月份；缺数据明确错误或已登记排除。

研究证据层记录artifact、opportunity、spec、run、review、package。不可变规格版本，批准后执行，哈希校验，幂等任务，等待数据状态。离线演示显式synthetic；真实数据输入要求manifest许可/时点/版本，不用演示替代论文结果。Paper targets始终列出原文目标/实测/状态。

来源适配器：手动论文＋arXiv，GitHub仓库元数据/README/提交，HF模型/数据集卡。外部内容不作为系统命令。真实模型按环境变量引用密钥、有限调用/超时、结构化证据输出；无凭据输出NOT_RUN。

审查过的本地配方可以直接运行以做数学核验；外部/生成代码仅可经审批后进入Docker隔离，缺Docker时拒绝隔离验收。不可将进程隔离冒充容器安全。无任意shell接口。

## 发布与验收

软件证据：测试、干净安装、CLI/API/UI、输入负例、哈希/审批、断点失败处理、来源在线探测、真实模型/容器能力分项记录。支持的能力必须实测；没有环境的条目BLOCKED/NOT_RUN。

研究证据：公式独立计算、五模型收敛/条款/种子、真实数据可得性审计、全部论文目标比较。只有原设定真实数据及独立复跑完成才可称完整复现。Wind/CSMAR历史条款/合约事件/因子不具备时，发布可运行研究软件和准确缺口清单，研究总状态BLOCKED，不改成PASS。工程审阅不能冒充第二位研究者真实数据复跑。

完整代码与状态如实推送用户指定仓库，使用正常提交且不强推，不提交原文全文、私有数据或密钥。首版若研究被数据阻塞，不打v1.0完整复现标签。
