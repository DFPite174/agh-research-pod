# AI驱动研究闭环实现计划

Goal: 人工触发、API模型生成候选、指定NT引擎优先、固定检验和预算内迭代，保留全过程证据。
Architecture: 新增受限策略表达式、日线数据适配、EQUITY引擎worker和research orchestration；复用现有Pod存储及HTTP客户端，不引入大型Agent框架。
Tech Stack: Python/AST/Pydantic/SQLite/FastAPI及指定独立NT环境。

- [x] 1. tests/test_research_agent.py 先覆盖表达式拒绝任意代码、数据hash、预算/轮数、证据引用和固定引擎路由。
- [x] 2. 实现strategy_rules.py和equity_data.py；全部输入有界、无未来数据调用、数据不静默填补。
- [x] 3. backends新增equity_worker.py并更新锁版本；真实引擎执行候选/基线，保留账本一致性与成本。
- [x] 4. research_agent.py实现严格模型响应、持久化任务/轮次、固定评价、总预算和停止；接入CLI/API/网页。
- [x] 5. 实际合成及本地A股数据受控模型任务验收，软件回归/构建/安装与独立审阅。
- [x] 6. 交付详细定义/接口/操作/状态/边界和项目借鉴说明；同步分支并核对远端。

完成记录：229测试、静态检查、受控模型+真实NT的合成与两只A股案例、研究包、构建/安装和实际HTTP通过。真实模型按用户选择NOT_RUN；任意Python未实现且Dockerdaemon不可用。独立静态审阅问题已修复并复核。代码和新定义同步现有分支，main不自动合并。
