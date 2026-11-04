# AGH ResearchPod

面向 Academic、GitHub、Hugging Face 的证据化研究工作台，支持通用量化时序实验，保留可转债论文为专用案例。

**当前定位：可运行的研究工程首版。原论文全历史实证仍被数据资格阻塞，不能称为完整复现，也没有实盘收益证据。** 合成演示、数学验证、替代数据研究和原设定复现使用不同标签。程序不从论文目标数字生成“实测结果”。

## 0.2 通用量化研究闭环

用户确认：通用研究闭环优先，案例围绕量化，不绑定作者。新增任务书 → 冻结量化规格 → 数据哈希审批 → 扩展窗口训练 → 双基线比较 → 复核 → 可重跑数据交付包 → 接收/拒绝/继续研究反馈。

内置 `quant` 配方接受 CSV 与来源 manifest；所有特征滞后一期，训练集内标准化，固定 ridge 参数，不自动搜索。支持不同数值目标与特征列；当前是单序列一步预测，不代表任意论文或跨截面组合都能自动实现。

```powershell
python examples/quant/validate.py
agh --root runtime/quant-work quant-run runtime/quant-validation/inflation-task.json
agh --root runtime/quant-work review RUN_ID --reviewer local --decision engineering_verified
agh --root runtime/quant-work package RUN_ID
agh --root runtime/quant-work receive PACKAGE_ID --receiver research --decision followup --reason "validate independent data"
```

`quant-run` 是明确执行授权：自动建立任务书、归档任务、冻结并批准该规格，然后执行；不自动复核或接收。网页也提供任务书、quant 规格和交付反馈表单。操作细节见 [通用量化指南](docs/general-quant.md)，本轮证据见 [升级验收](reports/general-acceptance.md)。

## 已实现的研究流程

来源导入与版本归档 → 机会与证据关联 → 不可变实验规格 → 批准 → 可信配方计算 → 原文目标比较 → 本地复核 → 哈希可校验交付包。

- BS、TF、LYW、LW、ZL 五模型；解析极限、三叉树与逐日路径模拟；条款近似及蒙特卡洛抽样误差随结果保存。
- 月末五分组、价格两端剔除、下一月持有收益、Newey–West(3)、市场与五类外部因子 alpha、Fama–MacBeth 计算工具。
- 392 个正文数值对照目标，21 项正文/附录目标清单。未计算项保留 NOT_RUN/BLOCKED；清单不等于全部稳健性实验已经实现。
- A/G/H 固定来源连接器、可选结构化模型分析、Tushare 权限/历史覆盖小样本探测。
- CLI、HTTP 接口和本地网页共用工作流；审批绑定规格、证据和数据清单哈希；幂等、失败记录与显式恢复。

## 安装与启动

支持 Python 3.12/3.13。建议使用独立环境。依赖锁与实际验证记录见仓库发行材料。

```powershell
git clone https://github.com/DFPite174/agh-research-pod.git
cd agh-research-pod
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\agh doctor
.venv\Scripts\agh demo
.venv\Scripts\agh serve --port 8010
```

Linux 使用 `python3.12`、`.venv/bin/python` 和 `.venv/bin/agh`。工作台默认仅监听 `127.0.0.1:8010`，面向单个受信任的本地使用者。

演示报告明确标记 **SYNTHETIC / ENGINEERING ONLY**，只验证计算和交付流程。运行数据默认写入 `runtime/`，不进入 Git。

## 首篇论文

- [期刊全文](https://nsd.pku.edu.cn/docs/20250227142007660959.pdf)
- [期刊在线附录](https://nsd.pku.edu.cn/docs/20250227142513335689.pdf)
- DOI：10.13821/j.cnki.ceq.2025.01.11。
- 原研究：2000-07 至 2022-06，696 只债，14,980 个券月观测，Wind/CSMAR 输入及外部因子。

```powershell
.venv\Scripts\agh case-status
.venv\Scripts\agh price examples/contract.json --model ZL --paths 10000 --seed 42
.venv\Scripts\agh data-audit --manifest PRIVATE_DIRECTORY/manifest.json
.venv\Scripts\agh case-run --manifest PRIVATE_DIRECTORY/manifest.json --idempotency-key first-approved-run
```

原始数据在用户授权的私有目录提供；格式见 [数据合同](cases/zheng-2025/data-contract.json) 和 [数据准备指南](docs/data-guide.md)。数据清单自称 `original_comparable` 不会自动获得科学认证。定价方法、样本/因子版本及全部目标仍须独立复核。

## Tushare 是否足够

官方接口提供转债行情、历史转股价、票息期、条款文本及国债即期曲线等候选输入；**基础积分权限不等于全部独立接口权限，也不证明老券历史完整或匹配原作者样本**。主要差距是历史条款/现金流时点、2000 年起即期曲线覆盖、存款利率和五组论文风险因子。

完整字段、权限、文档报价与购买前探测方案见 [Tushare 可行性审计](docs/tushare-feasibility.md)。通过你自己的私有环境配置 `TUSHARE_TOKEN` 后：

```powershell
.venv\Scripts\agh tushare-probe
```

无需在聊天或仓库中提供 Token。该命令只输出资格摘要，不公开原始记录；小样本成功仍返回 `QUALIFICATION_INCOMPLETE`，不能代表完整历史覆盖。

## 其他来源与模型

```powershell
.venv\Scripts\agh source-sync github lballabio/QuantLib
.venv\Scripts\agh source-sync arxiv "ti:convertible"
.venv\Scripts\agh source-sync huggingface-model sentence-transformers/all-MiniLM-L6-v2
.venv\Scripts\agh import LOCAL_PAPER.pdf
.venv\Scripts\agh analyze ARTIFACT_ID
```

可选模型配置仅引用 `AGH_LLM_BASE_URL`、`AGH_LLM_MODEL`、`AGH_LLM_API_KEY` 环境变量。无配置时返回 NOT_RUN；不会伪造“智能体完成分析”。模型输出必须引用已提供的证据 ID，仍须人工核实其事实。外部论文/README 的命令不是系统指令。

PDF 在送模型前提取有物理页码和原始哈希关联的正文；含无文本扫描页时返回 `BLOCKED_INPUT / NEEDS_OCR_OR_MANUAL_REVIEW`，不会将 PDF 二进制解码成正文。用户提供的首篇论文属于扫描件，当前方法规格来自人工逐页核实。另行核对的文本可导入为新证据并记录原文关联；没有自动 OCR 完成声明。长文本可显式设置 `--max-total-tokens 50000`，仍受总预算检查，超限不静默截断。

## 用户指定的数据与账户引擎

使用者明确配置的 DuckDB 优先于其他数据源。执行 `agh lake-audit --database PRIVATE_DATABASE` 可只读核查覆盖和缺字段。账户回测只走 [指定 NautilusTrader 后端](docs/backtest-integration.md)，执行 `agh engine-probe --engine-root LOCAL_ENGINE_CHECKOUT --python ENGINE_PYTHON` 核验当前版本。

本次用户提供的数据库快照有24只转债/240条日线，2017-01-03至2017-01-16；没有论文月末截面和完整历史条款。当前锁定引擎公共入口拒绝可转债，实际结果为 `BLOCKED_ENGINE_CAPABILITY`。详见 [只读数据库审计](reports/data-lake-audit.json) 与 [实际后端探测](reports/nautilus-engine-probe.json)。这些诊断不会产生虚构回测净值。

## 验证

```powershell
New-Item -ItemType Directory -Force runtime | Out-Null
.venv\Scripts\python -m pytest -q --basetemp=runtime/test-temp
.venv\Scripts\python -m pyflakes src tests
.venv\Scripts\python -m build
```

测试覆盖解析极限、现金/权益贴现、期限与票息、滚动条款、下修边界、MC 区间、排序/收益时点、因子日历、证据篡改、审批、幂等、缺数据阻塞、包关系与 HTTP 流程。网络连接、真实模型、供应商权限和容器能力分开记录，不能由模拟响应测试替代。

## 运行与安全范围

执行入口只接受经过审阅的内置 `demo` / `paper` 配方，没有任意 shell 或自动运行外部仓库的接口。当前内置计算在受信任进程中运行；取消阻止发布结果，不保证强杀已经开始的计算。中断恢复要求先停止 worker，再显式执行 `agh recover --workers-stopped`。

首版不声称无人值守执行恶意代码、多租户安全、自动发布策略或券商执行能力。Docker 不可用时环境检查明确标为 BLOCKED；Docker 隔离尚未通过验收前，不执行外部/生成代码。

## 文档

- [项目规格](docs/specification.md) · [实现计划](docs/implementation-plan.md)
- [定价方法](docs/pricing-methods.md) · [实证方法](docs/empirical-methods.md)
- [操作指南](docs/user-guide.md) · [数据准备](docs/data-guide.md)
- [验收状态](reports/acceptance.md) · [来源真实连接记录](reports/live-source-probes.json)
- [第三方与参考项目](THIRD_PARTY_NOTICES.md) · [安全说明](SECURITY.md)

自有代码采用 MIT License；数据源、论文、模型及其输出各自保留原有权利与使用限制。
