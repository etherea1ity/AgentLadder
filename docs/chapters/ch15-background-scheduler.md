# Chapter 15：Background Scheduler

语言：中文 | [English](./ch15-background-scheduler.en.md)

上一章：[Chapter 14：Durable Task System](./ch14-durable-tasks.md)

下一章：[Chapter 16：Subagent、Team 与 Worktree](../skills/roadmap.md#chapter-16---subagents-teams-and-worktrees)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Scheduler 只决定“何时产生哪一个 occurrence”；真正执行仍然必须先成为 Chapter 14 的 Durable Task，再交给同一个 `KlaraLoop`，所以重启、重复投递和长任务重叠都不会产生第二套执行真相。

![Klara Background Scheduler 状态流](../assets/ch15-background-scheduler.svg)

| 信号 | 决定 | 下一个状态 |
| --- | --- | --- |
| `next_run_at <= now` 且拿到 lease | 生成稳定 occurrence ID | `reserved -> enqueued` |
| 已有未终结 occurrence | `skip` 或最多 `queue_one` | `skipped_overlap` |
| 超过 misfire grace | `fire_once` 或 `skip` | task 或 `skipped_misfire` |
| Durable Task 终结 | 写 notification，再尝试投影 | `completed/failed/cancelled` |
| schedule 被 pause/cancel | 停止正常触发 | `paused/cancelled` |

## 快速体验

```powershell
.\scripts\dev.ps1 -Restart
```

打开 `http://127.0.0.1:5123`，先创建一条聊天，再从左栏进入 **Scheduler**。创建 one-shot、interval、daily 或 weekly automation，观察 timezone、recurrence、next run、last result、occurrence history，并实际执行 pause、resume、run now 与 cancel。

确定性门禁：

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.chapter15_cli `
  --json-out docs/reports/product/ch15-background-scheduler.json `
  --markdown-out docs/reports/product/ch15-background-scheduler.md `
  --markdown-en-out docs/reports/product/ch15-background-scheduler.en.md
```

预期为 `19/19` 检查通过、关键调度语义通过率 `1.000`、公共面秘密泄漏 `0`。

## 真实问题：时间到了不等于可以直接再跑一次

朴素 `while sleep()` 无法回答：进程在“创建任务前”和“创建任务后”崩溃分别怎么办；两个 worker 同时看见到期记录怎么办；纽约不存在的 `02:30` 或重复的 `01:30` 是哪一个瞬间；上一次还在运行时是否叠加；通知写入后投影聊天失败是否丢失。

本章把问题拆成四个持久化边界：schedule、scheduler lease、occurrence、notification。模型不决定这些边界，也不能用文字声称“已经安排”来替代数据库状态。

## 保持不变与本章新增

保持不变：`KlaraLoop` 仍是唯一 Agent loop；Chapter 14 Durable Task 仍是执行状态；RunService 仍把 Agent 运行投影到聊天；Permission、Evidence、Context 与 Skills 仍走既有装配。

本章新增：IANA 时区 recurrence、DST 策略、next-run、misfire、overlap、schedule lease、稳定 occurrence ID、重启扫描、通知 outbox 语义，以及读取同一 API 合同的 Scheduler Timeline。

## 从时间规则到唯一 occurrence

`src/klara/scheduler/models.py` 定义 four schedule kinds、状态、misfire/overlap policy 和 owner scope。`src/klara/scheduler/service.py` 的 `_occurrence_id` 使用：

```text
schedule_id | scheduled_for UTC | trigger -> SHA-256 prefix
```

相同预定瞬间被多个 tick 或重启再次看到时，`src/klara/scheduler/repository.py` 的 occurrence 主键只允许一条记录。流程先写 `reserved`，再以派生的 `task_id` 调用 `DurableTaskService.create`，最后改为 `enqueued`。若进程死在任意边界，下次 tick 会恢复 `reserved`，或把仍未终结的 `enqueued` occurrence 重新投递给幂等 RunService。

<details>
<summary>读取真实代码时要跟踪哪些状态</summary>

入口是 `SchedulerService.tick`。输入为 owner scope、worker ID、可选 dispatcher/notifier；输出是 `SchedulerTickResult`。`acquire_lease` 只把 token 的 SHA-256 写入 SQLite，完成或异常时按 token 删除 lease。成功 materialize 后 schedule 的 `last_occurrence_id` 与 `next_run_at` 在 CAS 更新中前进；拿不到 lease 时只增加 contention，不假装执行。

小实验：用两个 worker 对同一个到期 schedule 连续 tick；`tests/klara/scheduler/test_scheduler.py` 断言 occurrence 行和 task 都只有一个。

</details>

## Recurrence 与 DST 决策

daily/weekly 输入是 IANA timezone 加本地 `HH:MM`。`zoneinfo` 把 wall clock 往返验证为真实 UTC instant：

- spring-forward 的缺失时刻向前移动到第一个有效本地分钟；
- fall-back 的重复时刻固定选择较早 fold，一天只运行一次；
- interval 按 UTC 秒数推进；
- one-shot 保留调用者提供的带时区 instant。

这是一条显式产品策略，不声称适合所有日历业务。若业务要求“缺失时刻跳过”或“fall-back 运行两次”，应新增 policy，而不是悄悄改变现有语义。

## Misfire 与长任务重叠

late time 在 grace 内按普通 occurrence 执行；超过 grace 后：`fire_once` 立即物化一次并从现在计算下一次，`skip` 写一条无 task 的 `skipped_misfire` 审计记录。每个 tick 最多 catch up 一次，防止停机很久后形成任务风暴。

若 schedule 已有未终结 task，`skip` 只记录跳过；`queue_one` 还把 `queued_overlap=true`。当前 task 终结后，terminal reconciliation 清除此位并 `run_now` 一次。多次重叠仍只保留一个布尔待执行槽。

## Pause、Resume、Run Now、Retry 与 Cancel

pause 保留规则但移除正常 due 查询；resume 从当前时间重新计算合法 next run。run now 不篡改 recurring next run。failed occurrence 只有在对应 durable task 仍有 attempt budget 时才能 retry。cancel 停止后续触发并取消仍未终结的 occurrence task；API 同时请求取消对应聊天 run。

## 通知是可恢复投影，不进入模型上下文

task 进入终态后，Scheduler 先持久化确定性 notification ID。只有 notifier 成功返回后才写 `delivered_at`；失败时下一 tick 会重试。`RunService.inject_schedule_notification` 使用确定性 message ID 写入聊天，并设置 `model_visible=False`，所以用户看得到完成更新，但下一次模型调用不会把系统通知误当成用户事实。

这提供单进程数据库边界内的可恢复 at-least-once delivery 加幂等投影；它不是跨外部系统的 exactly-once 共识。

## API、后台 Worker 与 Scheduler Timeline

`apps/api/routes/scheduler.py` 暴露 state/create、pause/resume/cancel/run-now、occurrence retry 和 notification read。`apps/api/services/scheduler_runner.py` 以 daemon worker 串行 tick，生命周期由 FastAPI startup/shutdown 管理；工作在线程中执行，不在登录 shell 或请求主线程训练/阻塞。

`apps/web/src/components/SchedulerTimeline.tsx` 不保存第二份调度真相。它显示真实 timezone、recurrence、next run、last result、queued overlap、occurrence 和 notification，并在失败时明确说“未验证”，而不是做乐观成功动画。

## 测试与评估

```powershell
python -m pytest tests/klara/scheduler/test_scheduler.py tests/apps/api/test_scheduler_route.py tests/klara/eval/test_chapter15.py -q
npm --prefix apps/web test -- --run src/components/SchedulerTimeline.test.tsx
npm --prefix apps/web run build
```

覆盖 simulated time、spring gap、fall fold、misfire、overlap、pause/resume/cancel、reserved/enqueued restart、duplicate tick、notification delivery failure、scope isolation、API 和 UI。行为报告中的问题—参考—候选只是一致性 control probe，不是独立真人或模型裁判，也不支持“达到 ChatGPT 通用能力”的结论。

## 练习

1. 在 `tests/klara/scheduler/test_scheduler.py` 增加跨午夜 weekly case，并验证 weekday 按 schedule timezone 而非服务器 timezone。
2. 人为在 notification insert 后抛异常，重建 `SchedulerService`，证明 notification 仍会投影且聊天 message 不重复。
3. 在 UI 开启 200% zoom，用键盘完成 create、pause、resume 和 cancel，记录 focus 与横向溢出。
4. 为 `misfire_policy` 增加一个显式 UI 选择，但不得降低每 tick 最大 catch-up 为 1 的门禁。

## 限制与下一章

当前证明的是单主机 SQLite 与一个本地 tenant worker，不是多区域调度共识；worker 进程退出时依赖下一次应用启动恢复；模型 provider 长时间调用仍受 Chapter 8 与 Durable Task lease 约束。认证后的多租户 worker、PostgreSQL queue/outbox 属于 Chapter 18。

下一阶段先实现 Chapter 17 MCP，再实现 Chapter 16 bounded team/worktree：两者都必须通过 Permission Engine，并复用这里的 durable task 与 cancellation，而不能新增旁路执行器。
