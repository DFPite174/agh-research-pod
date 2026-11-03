# AGH首例 Implementation Plan

> For agentic workers: use subagent-driven-development for independent modules, then integration and final review. User authorizes implementation and GitHub sync.

**Goal:** 独立运行的研究工作台与五模型可转债论文复现配方，完整证据和诚实验收。

**Architecture:** 模块化单体，可信计算独立模块，模型/来源适配器，SQLite与内容哈希工件。所有运行共享版本、批准和研究结论规则。

**Tech Stack:** Python3.12+, numpy/scipy/pandas/statsmodels, FastAPI, SQLite, pytest, Docker optional restricted execution.

## Global constraints

依docs/specification.md；实际数据不伪造；测试先行；密钥只引用环境；商业原始数据及PDF不进Git；不强推；全部失败保留。

## Task 1 定价配方

Files src/agh_pod/pricing.py, tests/test_pricing.py。Consumes BondContract与本规格，produces price()与contract_from_dict()。先写解析极限/边界/独立公式/MC误差测试并看失败；实现BS、TF、LYW、LW、ZL；执行针对测试；记录歧义及numerical误差。不改研究门禁。

## Task 2 实证与对照

Files src/agh_pod/empirical.py, tests/test_empirical.py。输入标准DataFrame，输出组合收益与NW3检验、alpha、Fama-MacBeth、目标比较。先验证已知月度排序/时点/缺失/手算样本；实现；对照statsmodels。所有单位固定十进制，论文百分比只在报告显示时转换。

## Task 3 证据工作流

Files src/agh_pod/store.py, workflow.py, cases.py, tests/test_workflow.py。先测试未批准拒绝、版本不变、文件篡改、幂等、缺数据阻塞与交付完整性。实现本地数据库和包校验、演示和真实案例运行入口。论文目标表录入后与物理页人工核对。

## Task 4 来源和受限模型

Files src/agh_pod/sources.py, analyst.py, tests/test_sources.py, test_analyst.py。先写注入HTTP响应的限流/格式错误/凭据防泄漏/模型未知用量测试；实现A/G/H获取与结构化分析。实际连接单独运行存证，不将模拟HTTP测试当成在线能力。

## Task 5 交互与部署

Files cli.py, api.py, templates/, deploy/, tests/test_api.py。CLI/API共享workflow，服务端网页提供项目、证据、计划批准、运行与报告。先测试状态冲突、路径遍历、幂等；实现。启动网页检查实际截图。容器不可用时doctor正确阻断不受信任执行。

## Task 6 集成、发布、推送

pyproject、锁文件、CI、README、中英文数据合同、SECURITY/许可证/引用与限制。干净环境安装与复跑，全部测试，独立代码审阅，修复后重测。保存验收报告并commit，正常push；验证remote SHA与CI结果。不将未运行项标通过。
