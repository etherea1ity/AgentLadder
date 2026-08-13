# Chapter 16：Subagent、Team 与 Worktree

语言：中文 | [English](./ch16-subagents-teams-worktrees.en.md)

上一章：[Chapter 15：后台任务与调度器](./ch15-background-scheduler.md)

下一章：[Chapter 17：MCP 与外部工具](./ch17-mcp-and-external-tools.md)

路线图：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话理解本章

Klara 可以把显式任务包委派给干净上下文的一次性 Subagent，也可以创建带持久邮箱的队友；但创建、权限、任务归属、取消与代码 Worktree 仍然是由运行时控制的独立持久边界，不能由模型文字替代。

![Klara 有界 Team 运行时](../assets/ch16-team-boundary.svg)

| 边界 | 可以通过 | 不可通过 |
| --- | --- | --- |
| 父 Agent → Subagent | 标题、明确指示、白名单能力 | 父对话、隐藏推理、环境权限 |
| Permission → 子 Agent | 相同动作、更短期限、精确子任务 | 扩大范围、把 task grant 升为 standing |
| 子 Agent → 父 Agent | 邮箱里的公开摘要 | 完整内部转录或思维链 |
| Project → Worktree | 精确 base ref 与 `codex/` 分支 | 任意路径或 shell 拼接 |

## 快速体验

```powershell
.\scripts\dev.ps1 -Restart
```

打开 `http://127.0.0.1:5123`，在侧栏选择 **Team**，选择持久队友或一次性 Agent，再提交有界角色/任务。第一次创建会被阻断并进入 **Permissions**；批准精确动作后回到 Team 再次创建。界面读取真实 Agent、邮箱、任务关联、结果与 Worktree 状态。

运行确定性门禁：

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.chapter16_cli `
  --json-out docs/reports/product/ch16-subagents-team-worktree.json `
  --markdown-out docs/reports/product/ch16-subagents-team-worktree.md `
  --markdown-en-out docs/reports/product/ch16-subagents-team-worktree.en.md
```

## 为什么多调用一次模型不等于 Subagent

只有运行时明确决定上下文、工具、权限、任务 ID、取消和返回值之后，第二次模型调用才成为安全委派。复制整个父对话会静默分享无关私有状态；共用父权限会放大权限；把无限转录返回父上下文还会重新带入嵌入指令。

因此 `OneShotRequest` 只含标题、显式指示、白名单能力、可选父任务和模型选择。`KlaraOneShotExecutor` 用 `prior_messages=()` 启动 `KlaraHarness`。它只返回 `OneShotExecution.summary`；Team 记录保存公开摘要和 SHA-256，不保存 provider 隐藏推理。

## 一次性执行复用 Durable Task

`TeamService.spawn_one_shot` 先向 Permission Engine 请求 `team:{team_id}/spawn_one_shot`。批准后创建子 Durable Task、保存 Agent、写入一条任务分配邮箱消息，再启动有界 worker。worker 领取 Chapter 14 的真实 lease，报告进度，运行隔离 harness，完成任务，并向父邮箱发送一条 result。

取消不是把卡片隐藏起来。`stop_agent` 会标记取消并取消子 Durable Task，由既有生命周期关闭 active attempt。执行器失败且持有 lease 时会写入 failed task。这里没有第二套任务状态机。

## 持久队友与 MessageBus 语义

队友是持久身份，包含名称、角色、白名单能力、状态和可选任务。消息包含 sender、recipient、kind、body、task ID、按接收者单调递增的 sequence、创建与确认时间。读取必须匹配精确 tenant/owner/team/recipient；其他所有者只得到不透明的 not found。

邮箱是持久通信，不是共享 Memory。消息不会自动进入模型 prompt，也不会授予能力。`claim_next_task` 只扫描已经分配给该队友 agent scope 的 ready task，并通过 Durable Task 的 compare-and-swap lease 领取。

## 权限上浮实际是权限衰减

`delegate_authority` 直接调用 Permission Engine 已有的 `delegate`。子 grant 保持 tenant/actor，只绑定精确 child agent/task，动作不变、期限不能超过父 grant；被消费、拒绝、撤销或过期的父 grant 不能委派，task authority 不能升级为 standing authority。

Team 运行时本身也会为创建队友、生成一次性 Agent、创建和移除 Worktree 请求精确权限。模型说“已批准”无效；API 返回结构化 pending decision，Team UI 跳转到真实 Permission Center。

## Worktree 隔离

`create_worktree` 接收经过验证的 base ref，并要求 `codex/` 分支。目标路径由运行时生成在 `<project>/.klara/worktrees/<opaque-id>`，解析后再次检查包含关系。Git 使用参数数组和 `shell=False`，不会把 branch/path 拼到命令字符串。服务记录 creating/ready/failed/removing/removed 及验证后的 HEAD SHA。

移除需要单独权限，而且拒绝根目录外路径；它不会强制删除 dirty worktree，因此未提交修改会关闭失败。删分支与合并是独立的后续/用户动作。

## API 与 Team 工作台

`apps/api/routes/teams.py` 暴露 state、创建队友、生成一次性 Agent、邮箱发送/读取/确认、指定/自动任务领取、权限委派、停止和 Worktree 创建/移除。FastAPI 退出时会有界 join 子线程。

`TeamWorkspace.tsx` 不做乐观委派。它从 `/api/teams` 展示权限路径、Agent 类型/状态/能力、任务关联、摘要、父邮箱与 Worktree 状态；桌面和窄屏布局都把长摘要约束在中心栏。

## 测试与评测

```powershell
python -m pytest tests/klara/teams/test_team_service.py tests/apps/api/test_team_route.py tests/klara/eval/test_chapter16.py -q
npm --prefix apps/web test -- --run src/components/TeamWorkspace.test.tsx
npm --prefix apps/web run build
```

覆盖精确审批、干净上下文、仅摘要返回、scope 不透明、邮箱 cursor/ack、能力拒绝、durable claim、权限衰减、取消、真实 Git Worktree 创建/移除、API 投影和 UI fail-closed。

## 练习

1. 增加三名队友的 handoff，证明每一步只有指定邮箱能读到。
2. 在第一次进度后让 one-shot worker 崩溃，并通过 Durable Task lease 恢复。
3. 尝试包含 `..`、`@{` 或前导 option 的分支，证明 Git 启动前就被拒绝。
4. 增加只产出 patch artifact 的 clean-worktree merge proposal，应用仍要求单独的 owner decision。

## 限制与下一章

当前是有界单机编排运行时，不是分布式 worker fleet。持久队友具备身份、邮箱、权限与任务领取，但没有永远运行的自主轮询器。在后续评测与轨迹阶段能够公平比较之前，学习型多 Agent 路由明确排除。

Chapter 17 已通过同一个 Permission Engine 与不可信 observation 边界连接 MCP 外部工具；Chapter 18 将继续替换本地单用户持久化与队列假设。
