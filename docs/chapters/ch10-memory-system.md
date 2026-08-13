# Chapter 10：长期 Memory 系统

语言：中文 | [English](./ch10-memory-system.en.md)

上一章：[Chapter 9：Skills / 程序性记忆](./ch09-skills-procedural-memory.md)

下一章：[Chapter 11：RAG As Knowledge Tool](../skills/roadmap.md#chapter-11---rag-as-knowledge-tool)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

聊天历史只是当前上下文；只有用户显式要求保存，或自动候选经过审核后，内容才会进入带租户、类型、来源、时间、置信度和删除语义的长期 Memory。

![Klara 长期 Memory 生命周期](../assets/ch10-memory-lifecycle.svg)

| 操作 | 持久化语义 | 默认是否可检索 |
| --- | --- | --- |
| `remember` | 新建当前记录 | 是 |
| 自动候选 | 保存到独立候选区，等待审核 | 否 |
| `update` | 新建记录并 supersede 旧记录 | 只有新记录 |
| `forget` | 保留可审计历史，停止检索 | 否 |
| `delete` | 硬删除正文，只保留正文哈希审计 | 否，且正文必须为零残留 |

## 快速体验

```powershell
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:5123`，选择左侧 **Memory**。可以显式保存一条偏好，按类型和来源搜索，更新后观察新记录接管当前状态，再执行 forget 或带验证回执的 delete。

运行确定性门禁：

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.chapter10_cli `
  --json-out docs/reports/product/ch10-memory.json `
  --markdown-out docs/reports/product/ch10-memory.md `
  --markdown-en-out docs/reports/product/ch10-memory.en.md
```

## 为什么不能把聊天记录直接叫 Memory

完整聊天记录会混合临时讨论、已纠正事实、敏感内容和无关噪声。如果每条消息都自动保存，模型既无法解释“为什么记住”，也无法可靠执行更新与删除。Klara 因而区分：

```text
short-term context
  当前对话预算内的消息和压缩摘要

long-term memory
  经显式写入策略批准的结构化、可治理记录
```

`MemoryRuntimeController` 在每轮开始时会公开 `ordinary_chat_saved=false`；它不会扫描聊天并静默写入。模型调用 `memory_remember` 时也必须面对明确的工具描述：只响应显式 remember 请求。

## 五类记忆与完整记录

`MemoryKind` 不把所有东西放进一个向量桶：

```text
user_preference  用户偏好
stable_fact      稳定事实
episodic         发生过的事件
task             跨会话任务连续性
agent_learning   经审核的 Agent 经验
```

每个 `MemoryRecord` 保存：

- `tenant_id`、`user_id`、可选 `agent_id` 与 `session_id`；
- provenance 的来源类型、actor 与 source id；
- 创建/更新时间、`valid_from`、`valid_to` 与 TTL；
- confidence、sensitivity 与 metadata；
- `supersedes_id`、`superseded_by_id` 与 lifecycle status。

这些字段让 Klara 能区分“用户现在偏好浅色”与“用户三月时偏好深色”，而不是让新事实覆盖掉无法追溯的字符串。

## 作用域必须在检索之前生效

`SQLiteMemoryRepository` 的所有读取、修改和删除都要求同时匹配 `memory_id + tenant_id + user_id`。另一个租户即使猜到 id，也只会得到统一的 `memory_not_found`，不能借错误差异确认记录存在。

```text
API / tool authenticated scope
  -> SQL tenant_id + user_id filter
  -> lifecycle / TTL / agent filters
  -> retrieval ranking
```

作用域过滤绝不能放在排序之后，否则一次过度读取已经构成隔离失败。

## 更新、时间冲突与历史查询

`update` 不原地破坏旧事实。它会：

1. 验证旧记录属于当前作用域且仍 active；
2. 新建一条 current record；
3. 把旧记录标为 superseded，并写入 `valid_to`；
4. 建立双向 supersession link；
5. 分别写入不含正文的审计事件。

正常搜索只返回 active 记录；显式 `at_time` 历史查询允许 superseded 记录参与排序，并使用 temporal validity signal 判断当时是否有效。

## 自动候选必须经过审核

自动提议和正式 Memory 使用两张表。`propose_candidate` 只创建 `pending` 候选，不会出现在 `search`。只有 `review_candidate(... approve=True)` 才会把它变成正式记录；拒绝会硬删除候选正文，同时留下内容哈希审计。

这种结构支持以后在 Stop hook 上生成候选，却不会让模型自己决定永久保存全部对话。

## Hybrid 检索及可解释消融

仓库原生 ranker 组合五个信号：

```text
hybrid score =
  0.30 lexical
  0.34 deterministic semantic hash-vector
  0.14 entity overlap
  0.10 recency
  0.12 temporal validity
```

每条结果包含 score components，便于定位是召回失败还是排序失败。Chapter 10 同一 fixture、同一 top-k 下比较：

- full context；
- recent window；
- lexical-only；
- vector-only；
- Klara hybrid；
- Mem0-compatible 简化检索基线。

这里的 `mem0_compatible` 只是公开、固定的 vector + recency 兼容基线，不等于 Mem0 官方系统，也不允许写成“击败 Mem0”。

## Mem0、MEM1 与公开 Benchmark 合同

最终公平实验必须让所有系统使用完全相同的 answer model、题集/隐藏集、最大上下文、生成长度、top-k、推理预算和 grader。计划执行：

| Benchmark | 主要能力 | 官方来源 |
| --- | --- | --- |
| LoCoMo | 长期会话 QA、事件和多跳 | `snap-research/locomo` |
| LongMemEval | 提取、多会话、更新、时间、拒答 | `xiaowu0162/LongMemEval` |
| MemoryAgentBench | 准确检索、测试时学习、长程理解、冲突 | `HUST-AI-HYZ/MemoryAgentBench` |
| BEAM | 128K 到 10M 的十类长期能力 | `mohammadtavakoli78/BEAM` |

竞争系统使用官方执行路径：Mem0 对接 `mem0ai/memory-benchmarks`；MEM1 对接 `MIT-MI/MEM1` 的官方 checkpoint/rollout。Chapter 10 只冻结 adapter contract，并把两者明确标为 `not_executed`。完整对比在同一 answer model 冻结后运行，BEAM 从 128K/100K 级别开始并转到 HKU。

报告至少包括 answer quality、retrieval recall/precision、temporal/multi-hop accuracy、tokens、P50/P95 latency、cost 和 storage growth；任何未成功执行的系统都必须显示未比较，而不是补录论文数字。

## 删除证明与审计边界

`delete` 先取得正文哈希，再从正式记录表硬删除，然后扫描持久化 payload，返回：

```json
{
  "deleted": true,
  "raw_content_occurrences": 0,
  "deletion_verified": true
}
```

审计表保存 operation、owner、actor、record id、时间和 `content_sha256`，不保存已删除正文。测试会直接搜索 SQLite payload；发现一次原文残留就失败。

## API、工具、Trace 与 UI

产品 API 支持 list/create/search/update/forget/delete。Owner 在 Memory 页面可以看到正文与 provenance；普通 runtime trace、SSE 和活动投影只显示 memory id、类型、状态、数量与删除证明，不能出现查询词、正文或 provenance note。

`ToolResult.public_content` 使模型在当前运行中看到授权检索正文，同时 JSONL trace 只得到替代后的内容安全摘要。这一通用核心能力只决定“同一 observation 的模型视图与公共视图可以不同”，不包含任何 Memory 业务规则。

## 本章验证什么，不验证什么

本章通过意味着：五类记录、作用域、来源、时间冲突、候选审核、TTL、更新/遗忘/删除/导出/审计、混合检索、API、Runtime 安全投影和响应式 UI 已有真实实现与回归。

本章不意味着 LoCoMo、LongMemEval、MemoryAgentBench 或 BEAM 已完整跑完，也不意味着 Klara 已击败 Mem0 或 MEM1。这些结论只能来自冻结 answer model 后的统一公开/隐藏评测。

Chapter 11 的通用文档 RAG 按本项目范围标记 `deferred_by_scope`，不能借 Memory 的检索能力冒充完成；下一阶段进入 Chapters 12–13 的证据控制运行时。
