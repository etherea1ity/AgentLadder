# Chapter 18：生产运行时与评测桥接

语言：中文 | [English](./ch18-production-runtime-and-eval-bridge.en.md)

上一章：[Chapter 17：MCP 与外部工具](./ch17-mcp-and-external-tools.md)

下一步：[Lab A：轨迹数据集与评测](../skills/roadmap.md#lab-a---trace-dataset-and-evaluation)

路线图：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话理解本章

Klara 现在有了一条生产形态路径：签名身份拥有每一个会话和任务，worker 只能凭可过期的 CAS 租约执行，终态与通知在同一事务提交，只有经过授权和脱敏的 trace 才能进入评测或训练。

![Klara Agent 行为评测合同](../assets/ch18-agent-eval-contract.svg)

| 边界 | 运行时保证 |
| --- | --- |
| credential → principal | 校验签名、issuer、audience、有效期、tenant、user 与 role |
| principal → data | owner 查询同时过滤 tenant 和 user，外部对象保持不可见 |
| queue → worker | 只有持有未过期租约的人能 heartbeat 或结束任务 |
| job → notification | 终态迁移与 Outbox 写入共享一个事务 |
| public trace → dataset | 检查所有权、路径包含、schema、脱敏、连接、split 与哈希 |
| baseline → candidate | fixture/split 哈希必须一致，P0 或资源回退直接失败 |

## 快速体验

原有 `/api` 路径继续作为各章 UI 的本地学习适配器；新的 `/api/production` 路径独立要求认证，是部署与 worker 应使用的路径。

```powershell
$env:KLARA_AUTH_MODE = "development"
\.\scripts\dev.ps1 -Restart
```

在同一台工作站申请短期开发 token：

```powershell
$tokenResponse = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/production/auth/dev-token `
  -ContentType application/json `
  -Body '{"tenant_id":"demo-tenant","user_id":"demo-user","roles":["owner","operator"]}'
$headers = @{ Authorization = "Bearer $($tokenResponse.access_token)" }
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/production/whoami -Headers $headers
```

`/auth/dev-token` 只允许 loopback，并且在 `KLARA_AUTH_MODE=production` 时消失。生产启动不会自行制造签名 key：部署必须通过秘密通道提供 `KLARA_AUTH_SIGNING_KEY`。它绝不能进入 Git、TOML、job payload 或 trace。

运行确定性门禁：

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.chapter18_cli `
  --repository-root . `
  --json-out docs/reports/product/ch18-production-runtime.json `
  --markdown-out docs/reports/product/ch18-production-runtime.md `
  --markdown-en-out docs/reports/product/ch18-production-runtime.en.md
```

## 1. Auth 是运行时边界

`AuthService` 在 Klara 的可信部署边界使用紧凑、带版本的 HMAC-SHA256 bearer 格式。它先检查固定 header、常量时间签名、token schema、issuer、audience、签发时间、过期时间与最长寿命，之后才生成 `Principal`。Principal 包含 tenant、user、roles、token ID 和到期时间；公共投影不会返回 token ID 或 credential。

角色刻意保持很小：`owner` 和 `operator` 创建、查看自己的 session/job，`worker` 领取本 tenant 的任务，`evaluator` 导出自己拥有的轨迹，`admin` 查看无 payload 的聚合指标。`admin` 可以满足角色检查，但不会绕过 repository 的 owner 条件。托管 OIDC 或 workload-identity gateway 可以负责认证人并签发内部 credential；身份提供商本身的部署不属于仓库代码。

开发签发端不是生产登录系统。它只为了在一台工作站上复现实验，不接收密码，不能远程调用，在 production mode 中不存在。

## 2. 带版本持久化与不透明租户隔离

`ProductionRepository` 在 `BEGIN IMMEDIATE` 下执行不可变 SQLite migration，并把每个 migration 的 checksum 写入 `schema_migrations`。重启可以幂等执行；如果已经应用过的 migration 文本被改动，启动会失败，而不会静默修改旧库。

Session 和 job 都持久化 `tenant_id`、`owner_id`。owner API 的每条查询都同时带两个过滤条件；同 tenant 的另一个 user、另一个 tenant 中同名的 user 都只会得到 not found。Worker 只有在 `worker` 角色检查之后才进入单独的 tenant-scoped 查询。公共 job 记录只返回生命周期元数据与 payload hash，不返回问题、结果、lease hash 或 worker credential。

当前 repository 使用 SQLite WAL 证明单主机可靠性。Service/repository 分层是有意保留的：部署可以添加遵守同一 CAS 与 Outbox 合同的 PostgreSQL adapter，但不能削弱 owner predicate 或租约校验。

## 3. 幂等队列、租约、取消与事件流

入队必须提供 tenant/user 内唯一的 `Idempotency-Key`。同一个 key 与完全一致的 canonical payload 会返回原 job；同 key 不同内容直接失败。Payload 与 result 都限制在 64 KiB。

Claim 在 immediate transaction 中执行：先恢复过期任务，再选择一个可用行，把它从 `queued` 改成 `running`，增加 attempt，只保存随机租约的 SHA-256，并把原始 lease 一次性返回给 worker。Heartbeat、complete、fail 都校验 hash 与有效期；伪造或过期租约不能结束任务。

`ProductionQueueWorker` 是冻结 Agent runtime 的适配边界。Executor 只能看到受限 payload、稳定 job/run ID、attempt 次数、协作式 `cancel_requested` 探针和 `heartbeat()`；它看不到原始 lease。异常只持久化异常类型作为公共 error code，provider 错误文本不会进入数据库。

运行中任务采用协作式取消，排队任务立即取消。公共 job events 保持单调序号，只含 state、attempt、error code 或 result hash，不含 prompt/result 文本。`/events/stream` 先重放已有事件，再轮询新事件，输出 SSE ID，并在终态或客户端断开时关闭。

## 4. Transactional Outbox

Job 进入终态和 `prod_outbox` 插入发生在同一个数据库事务。事件只含 job ID、run ID 和终态。Delivery 有独立的 hash 租约和 acknowledgement；delivery 进程崩溃后可以重新领取，而不需要重跑 Agent job，伪造 delivery token 也不能确认。

这把任务 effect 与通知 effect 分开了，但不声称任意外部系统都能 exactly-once；consumer 仍须用 `event_id` 做幂等键。

## 5. 授权轨迹导出

`TrajectoryExportService` 首先证明 job 属于调用者，请求的 trace 也必须 resolve 在配置的 trace root 下。Exporter 只选择这个 job 的 run，按 seq 排序，再调用 Chapter 3 的 trajectory projection。

数据集仅保留：

- 生命周期状态与受限 outcome 标签；
- 工具名称和 tool-call 连接，不含参数或返回内容；
- 显式 source/claim ID；
- 获准的 latency、token、cost 数值字段。

它丢弃 raw prompt、final answer 文本、tool arguments/results、provider reasoning 和 private reference。验证器要求 seq 连续、run ID 单一、turn 单调、每个 tool start 都有 terminal、source/claim 已声明，并执行 secret pattern 扫描。稳定 group hash 决定 train/validation/test，避免看到结果后人工移动措辞变体。

每次 export 获得 opaque ID 和 tenant-hashed 目录。`manifest.json` 连接 source trace hash、job payload hash、run lineage hash、schema 版本、split counts、dataset hash 与 privacy 声明。Repository 只记录 dataset/manifest 哈希用于审计，不重复保存内容。

## 6. 冻结回归比较

`klara.eval.regression_cli` 无需前端即可比较 baseline 与 candidate behavior report。Fixture hash、split hashes、schema 或 observation 数量不同都会拒绝比较。Candidate 必须在 critical、overall、normal、reference、independent judge、human acceptance、P0 与 severe mismatch 上保持非劣。

默认还限制 candidate/baseline 总 latency 不超过 `1.25`、token 不超过 `1.10`、cost 不超过 `1.10`。Baseline 为零时仍然严格：candidate 可以继续为零，但不能引入原本不存在的成本。JSON 是唯一事实源，中英文 Markdown 只是镜像。

本章生成的 control comparison 在两侧使用同一份冻结报告，只证明比较器与 anti-drift 检查能工作。它还不是最终的当前 Agent 对 GPT 行为判断；真实 observations、独立 grader 与人评要在 Agent Product Freeze 执行。

## 7. 可观测性与隐私

生产 middleware 生成或限制 request ID，把它返回给调用方，添加 `nosniff` 与 `no-store`，并聚合 method、route template、status class 与 duration。Metric label 不会包含 tenant、user、prompt、token、job ID、异常文本或 URL query；只有 `admin` 能查看聚合指标。

Audit row 保存 tenant、actor、action、target type、target-ID hash、request-ID hash 与时间；刻意不保存 bearer、request body、result 和隐藏模型推理。

## 测试与复现

```powershell
python -m pytest `
  tests/klara/production `
  tests/apps/api/test_production_route.py `
  tests/klara/eval/test_regression.py `
  tests/klara/eval/test_chapter18.py -q
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

定向测试覆盖签名篡改/过期、生产缺 key、角色分离、同 tenant/跨 tenant 不透明隔离、migration checksum、idempotency collision、队列恢复、伪造 lease、heartbeat、取消、worker retry、秘密不落盘、Outbox acknowledgement、export 路径包含、trace 脱敏/连接/哈希、API projection 与回归故障注入。

## 小实验

1. 用 fake clock 越过 worker lease，确认第二个 worker 能恢复任务，而第一个 lease 无法再 complete。
2. 用同一 idempotency key 修改 `maximum_steps`，确认队列拒绝。
3. 在临时 trajectory 对象加入 `authorization`，确认 privacy validator 给出准确路径。
4. 把 candidate token 总数提高到 baseline 的 `1.11×`，确认即使所有 task success 不变，报告仍失败。
5. 实现 PostgreSQL repository adapter，并复用完全相同的 service/evaluator 合同。

## 限制与下一阶段

本章证明单主机上的认证多用户隔离与 durable queue 语义，不负责部署 identity provider、多区域共识、托管数据库静态加密或外部消息 broker。这些是部署选择，不是削弱 repository 合同的理由。

学习策略仍然不能接管 Agent runtime。下一步 Lab A 通过本桥收集真实、许可清楚、检查 contamination 的轨迹并冻结评测集；只有完整 Agent Product Freeze 通过后，才允许启动 HKU 训练。
