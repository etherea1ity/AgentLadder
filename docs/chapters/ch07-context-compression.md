# Chapter 7：Context Compression

语言：中文 | [English](./ch07-context-compression.en.md)

上一章：[Chapter 6：System Prompt 与 Context Assembly](./ch06-system-prompt-and-context-assembly.md)

下一章：[Chapter 8：Error Recovery 与 Fallback](../skills/roadmap.md#chapter-8---error-recovery-and-fallback)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

当历史超出冻结预算时，Klara 在下一次 LLM 调用前先触发 `PreCompact`，压缩旧工具结果、把更旧对话汇成私有摘要，并尽量原样保留最近消息和当前请求。

![Klara Chapter 7 Context Compression](../assets/ch07-context-compression.svg)

| 预算信号 | Runtime 行为 |
| --- | --- |
| 估算未超限、旧工具结果也不大 | 保持 transcript 不变 |
| 旧工具结果超过字符上限 | 保留工具名和 call id，正文裁剪并附 digest |
| 总估算超过 transcript budget | 汇总安全前缀，保留近期窗口 |
| 单条最新消息本身过大 | 保留头尾与 digest，强制适配硬窗口 |
| 即将压缩 | 先发 `PreCompact` hook，再产生公开预算证据 |

## 快速体验

```powershell
.\scripts\dev.ps1
```

正常短对话会出现低调的 `Context ready` 状态。长历史触发压缩后，它变成 `Context compacted`，显示估算 token、预算和被汇总的旧消息数量。这个面板永远不展示摘要正文。

## 为什么固定保留最后 N 条不够

原先 API 只保留最后 12 条已完成消息。它看似简单，却把消息条数误当成 token：12 个巨大网页结果可能溢出窗口，13 条很短的决策又会无故丢掉第一条。更严重的是，截断没有事件、没有摘要、没有 hook，无法解释模型为什么忘记。

Chapter 7 改为预算驱动：

```text
max_input_tokens
- reserved_system_tokens
- reserved_output_tokens
= transcript_budget_tokens
```

估算器使用稳定 JSON 表示的字符数除以配置化 `chars_per_token`。它不是 tokenizer 精确计数，因此报告明确写 `estimated`；硬约束则为后续真实 provider token 计数保留替换点。

## 机制一：压缩顺序保护近期意图

压缩采用确定性优先级：先微压缩近期窗口之外的工具 observation，再从安全前缀移除旧消息并生成 extractive session summary，最后只在仍超预算时裁剪单条巨大消息。

当前用户请求位于 transcript 尾部，因此优先保留。删除前缀时还会跳过连续 tool result，避免留下没有对应 assistant 请求的孤儿工具消息。

<details>
<summary>查看预算算法</summary>

```text
src/klara/context/policy.py
src/klara/context/budget.py
tests/klara/context/test_budget.py
```

边界测试覆盖近期消息保留、旧工具 `tool_call_id` 保留、摘要 hash、单条超大消息和不可成立的预算配置。

</details>

## 机制二：PreCompact 位于模型调用之前

初始历史也必须在第一轮调用前检查，而不是只在工具执行之后检查。`KlaraLoop._prepare_messages` 先询问 controller 是否需要压缩；如果需要，它依次发出：

```text
pre_compact.started
-> HookManager.pre_compact(...)
-> ContextController.prepare_next_turn(...)
-> context.budget_evaluated / context.compacted
-> pre_compact.completed
-> llm.started
```

final answer 被 controller 拒绝并追加反馈时也走同一准备路径，长运行不会从这条支路绕过预算。

## 机制三：摘要是上下文，不是新指令

摘要使用带角色标签的抽取式内容，不额外调用付费模型。它在 `<session_context>` 内明确标成 prior conversation context，并指示模型不要把摘要当成新指令。连续压缩会把上一个摘要作为输入，避免已经省略的事实彻底消失。

公开 `context.compacted` 只包含压缩前后估算、预算、消息数量、微压缩/硬裁剪计数、摘要存在状态和 SHA-256。正文只存在于 controller 私有状态和下一轮 system prompt。

<details>
<summary>查看 Hook、trace 与 UI</summary>

```text
src/klara/core/hooks.py
src/klara/core/loop.py
apps/api/services/run_event_projector.py
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/ContextBudgetStatus.test.tsx
```

UI meter 对百分比做 100% 封顶，并只读取数字字段；缺少 context 事件时完全不渲染，不会猜测模型窗口。

</details>

## 运行与验证

```powershell
$env:PYTHONPATH = "src;."
python -m pytest tests/klara/context tests/klara/core/test_loop.py tests/apps/api/test_run_service_history.py -q
python -m klara.eval.chapter06_07_cli `
  --repository-root . `
  --json-out docs/reports/product/ch06-07-context.json `
  --markdown-out docs/reports/product/ch06-07-context.md `
  --markdown-en-out docs/reports/product/ch06-07-context.en.md
Push-Location apps/web
npm test
npm run build
Pop-Location
```

门禁向真实产品会话写入 10 条长历史，检查首次 LLM 输入少于原始 11 条、当前请求仍在尾部、摘要只在 system prompt、`PreCompact` 在 `llm.started` 之前、API 恰好投影 started/completed 两个 placement 事件。

## 小实验

1. 把一个旧 `web_fetch` 结果扩到 900 字符，确认 call id 不变且内容出现 digest marker。
2. 把 `recent_messages` 从 10 改成 4，比较被汇总数量与模型可见近期轮次。
3. 用只有一条超大当前消息的 transcript，确认头尾仍在且估算不越界。
4. 在 trace 与 SSE 里搜索私有 marker，确认只能找到 `summary_sha256`。

## 本章边界与下一章

抽取式摘要是确定性预算机制，不等同于高质量语义记忆；它也不写入长期 Memory，不检索 RAG，不学习选择策略。Chapter 8 会处理 provider retry/fallback、工具错误分类和可恢复失败，同时复用本章的有界上下文。
