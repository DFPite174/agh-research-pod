# 本地工作台与命令行

AGH ResearchPod 0.1 是单个受信任用户的本地研究工作台。启动地址固定为 `127.0.0.1`；没有组织账户、多租户或公网部署验收。工作台中的审批与复核者是本地声明身份。原文 PDF、商业原始数据和密钥不应加入 Git。

## 启动与最短操作路径

在已安装本项目及依赖的 Python 环境运行：

```powershell
agh --root ./runtime doctor
agh --root ./runtime serve --port 8010
```

浏览器打开 `http://127.0.0.1:8010`。全局选项 `--root` 要放在子命令前；不同 root 是不同 SQLite 与哈希证据库。默认 root 是当前目录的 `./runtime`。

页面包括五个区块：研究机会、证据库、规格与批准、运行与复核、论文目标与缺口。先创建机会，选择内置配方并冻结新规格，批准该规格，再提交运行。提交后阅读“操作回执”，点击“刷新工作台”查看最终状态。页面以 JSON 请求调用同一应用逻辑，标题等外部文本使用 HTML 转义，不将来源内容当成网页代码执行。

网页对同一个不可变规格使用固定的 `ui:SPEC_ID` 幂等 key，因此重复点击或刷新后再次提交会返回同一运行。需要有意重新运行时，使用 CLI `run SPEC_ID --idempotency-key NEW_KEY`，或冻结新规格。

`demo` 配方使用合成数据（Synthetic）；它只核验软件与数学行为。`paper` 配方依赖 manifest 指向的真实历史数据与条款。缺少数据时应保留 BLOCKED / NOT_RUN；成功生成证据包不表示论文完整复现成功。

## 精确命令

所有命令支持 `agh --help` 或 `agh 子命令 --help`。若环境没有安装 console script，可在源码根目录设置 `PYTHONPATH=src`，使用 `python -m agh_pod.cli`。

| 命令 | 行为 |
|---|---|
| `agh [--root DIR] serve [--port 8010]` | 固定监听 127.0.0.1；仅端口可选 |
| `agh [--root DIR] doctor` | JSON 输出 Docker 可执行文件及守护进程可达性、凭据名称和是否存在；不输出密钥值 |
| `agh [--root DIR] demo` | 创建合成能力评价机会 → 固定 seed=7 的 demo 规格 → 批准 → 执行 → 记录工程复核 → 导出并验证证据包 |
| `agh [--root DIR] case-status` | 输出案例目标登记与研究缺口状态 |
| `agh [--root DIR] tushare-probe` | 调用少量已登记的 Tushare 资格探测，输出条数/日期范围等摘要；无 TUSHARE_TOKEN 为 NOT_RUN，不发请求 |
| `agh [--root DIR] analyze ARTIFACT_ID [ARTIFACT_ID ...]` | 读取并核验工件哈希，保留工件 ID 作为模型证据引用，运行有限预算结构化分析；配置缺失为 NOT_RUN |
| `agh [--root DIR] import PATH [--title TITLE]` | 归档本地 PDF/TXT/Markdown 文件，最大 25 MB；只存储证据，不执行 |
| `agh [--root DIR] source-sync SOURCE REFERENCE` | 在线获取来源，将返回内容以哈希工件归档 |
| `agh [--root DIR] list KIND [--limit 200] [--offset 0]` | 查看持久化对象；KIND 为 opportunity/artifact/spec/run/review/package；limit 1–1000 |
| `agh [--root DIR] approve SPEC_ID` | 批准 planned 规格；已批准规格不可再次批准或原地改写 |
| `agh [--root DIR] run SPEC_ID [--idempotency-key KEY]` | 执行已批准规格；同规格同 key 返回原运行，不重复执行 |
| `agh [--root DIR] worker --once` | 按最早入队顺序执行本次扫描到的全部 queued 任务，不受历史终态记录数量限制；执行后退出 |
| `agh [--root DIR] recover --workers-stopped` | 操作者已停止全部 worker 后，显式将遗留 running 任务标记为 interrupted |
| `agh [--root DIR] package-verify PATH` | 核验目录中的证据包文件哈希与必要文件；不产生科学复现认证 |
| `agh [--root DIR] price PATH [--model BS] [--steps 200] [--paths 10000] [--seed 42]` | 读取合约 JSON，运行 BS/TF/LYW/LW/ZL 中指定模型，输出数值与方法状态 |
| `agh [--root DIR] data-audit --manifest PATH` | 调用案例数据审计；实际结果以审计字段为准 |
| `agh [--root DIR] case-run --manifest PATH [--idempotency-key KEY]` | 创建 paper 机会与规格、记录批准、执行 manifest 对应的内置配方；该显式命令是对新规格的执行授权 |

`source-sync` 的 SOURCE 可选 `arxiv`、`github`、`huggingface-model`、`huggingface-dataset`。REFERENCE 采用对应适配器支持的论文标识或仓库标识；例如：

```powershell
agh --root ./runtime source-sync arxiv 1706.03762
agh --root ./runtime source-sync github microsoft/RD-Agent
agh --root ./runtime source-sync huggingface-model Qwen/Qwen2.5-7B-Instruct
agh --root ./runtime source-sync huggingface-dataset HuggingFaceFW/fineweb
agh --root ./runtime import ./paper.pdf --title "论文原文（本地许可副本）"
```

来源联网成功仅证明适配器可达及取得来源证据，不代表执行了外部代码或验证了其声明。doctor 只检查环境变量是否存在，不证明凭据有效；Docker daemon 不可达显示 BLOCKED。该 CLI 不提供外部 shell 或任意代码执行命令。

模型分析使用私密环境变量 `AGH_LLM_API_KEY`、`AGH_LLM_MODEL`，可选 `AGH_LLM_BASE_URL`；不从工件或命令行参数读取密钥。模型仅得到有标识的来源文本，不获得 shell/工具；输出引用校验、预算和未知用量由分析模块记录。PDF 原始字节应先由可信提取过程生成文本工件，再送入分析；本命令不会自动声称完成 PDF 的结构化解析。

Tushare 小样本探测只提供资格证据摘要，不导出私有原始行。即使返回 OBSERVED 也不能证明覆盖完整论文时期、严格时点质量或具备全部数据许可。

`case-run` 首次请求创建新的不可变规格。相同 root、manifest 绝对路径和 idempotency key 的重试返回原运行，保留原来的成功、失败或阻塞结果，不创建另一规格；同一 key 指向另一 manifest 路径返回冲突。需要有意重新实验时使用新 key。manifest 内容后续改变不会改写已经完成的旧请求；新实验仍应单独创建并批准规格。

输出为 JSON。一般成功返回退出码 0；显式运行失败/证据包核验失败返回 1；输入、路径、状态或依赖错误返回 2，并向 stderr 输出 `error` / `error_type`。BLOCKED 是可报告的研究结果状态，不应仅以进程退出码当成成功复现。`serve` 前台持续运行，Ctrl+C 停止。

## HTTP API

通过 `create_app(root)` 构造 FastAPI 应用。请求体为严格 JSON：未知字段与不匹配类型拒绝，不把字符串或布尔值强制转换为整数。API 文档可在本地 `/docs` 查看。

| 方法与路径 | 请求与结果 |
|---|---|
| `GET /v1/health` | 本地服务健康与研究认证边界 |
| `GET /v1/opportunities?limit=200&offset=0` | 机会列表 |
| `POST /v1/opportunities` | `{title, research_type, problem?}`；research_type 为 investment_research / capability_evaluation；201 |
| `GET /v1/artifacts?limit=200&offset=0` | 工件元数据列表；不提供文件下载路径读取接口 |
| `POST /v1/opportunities/{id}/specs` | `{recipe, seed?, dataset?, steps?, paths?}`；recipe 只能 demo / paper；201 |
| `POST /v1/opportunities/{id}/artifacts` | `{artifact_id}`；关联已经归档的工件与机会，缺少任一对象返回 404；200 |
| `POST /v1/specs/{id}/approve` | `{}` 或省略请求体；200 |
| `POST /v1/specs/{id}/runs` | `{}` 或省略请求体；可用 `Idempotency-Key` 标头；202 返回 queued 记录，随后 BackgroundTasks 执行 |
| `GET /v1/runs/{id}` | 查询持久化状态、结果或失败原因 |
| `POST /v1/runs/{id}/cancel` | `{}`；仅 queued/running；200 |
| `POST /v1/runs/{id}/reviews` | `{reviewer, decision}`；201 |
| `POST /v1/runs/{id}/packages` | `{}`；要求可接受复核；201 |

复核 decision 为 `engineering_verified`、`needs_data`、`rejected`、`scientifically_reviewed`。只有存在可复核科学结果时，才可记录科学复核；工程复核无法升级研究证据层级。

对象不存在返回 404；状态冲突、幂等 key 与不同规格冲突、完整性错误返回 409；字段错误及非法预算返回 422。seed 范围 0–2³²−1，steps 为 2–2000，paths 为 2–100000。页面和 API 均不暴露任意 shell、文件系统浏览或代码执行入口。

API 的后台任务是本地进程内执行机制。持久化 queued/running 状态保存在 SQLite；进程停止后不会有远程队列自动续跑。可用 `worker --once` 执行 queued 任务；所有 worker 已停止且确认运行进程不再工作后，才运行 recover 记录中断。取消阻止结果最终发布，已经进行中的可信计算可能继续结束。不要同时把多个未受协调的 worker 当作生产调度服务。

不同内置任务可并行运行；steps/paths 限制每个任务的预算，没有全局单活任务承诺，也没有生产调度服务的并发配额与资源隔离验收。

## 结果解释

证据包包括运行、冻结规格、机会、复核和清单哈希。它用于核对本地研究过程，`scientific_replication_certified` 始终不因导出而变成 true。缺少 Wind/CSMAR 历史条款/事件、许可、因子、原设定完整样本与独立复跑时，应继续把论文完整复现记录为 BLOCKED。
