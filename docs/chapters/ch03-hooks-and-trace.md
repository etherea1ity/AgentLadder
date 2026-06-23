# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Chapter 3 不是给 loop 加更多业务规则，而是把 agent 运行时变成可观察的系统：core loop 继续只负责模型、工具和停止条件；hooks 负责生命周期插点；trace 负责记录公开事件；前端把同一条公开事件流分成三层展示。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

## 三层界面

### 1. Top Thinking Trigger

用户主路径只看到一个很轻的 GPT-like 入口：

```text
运行中：  mini Klara + Thinking... + timer
完成后：  mini Klara + Thought for X >
```

它不展开工具链路，不显示 raw payload，也不展示 developer trace。点击正文区域不会展开；只有右侧 chevron / button 会打开 Activity Drawer。

对应代码：

```text
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/styles/klara.css
```

### 2. Activity Drawer

Activity Drawer 是公开活动摘要，不是模型私密思考。它展示两类内容：

```text
Klara thinking  -> narrator 基于完整 public trace 生成的 2-5 条公开 activity items
Agent activity  -> API projection 层从真实 runtime events 派生的 activity_item_upserted
```

即使主模型没有 stream、没有 thinking token，Activity 也能基于 runtime events 显示真实中间链路。例如：模型调用开始、web_search 返回候选源、web_fetch 读到页面文本、最终进入回答生成。

Activity item 必须带 `evidence_event_ids`，只能引用已经发生的公开事件。它不能暴露 raw tool arguments、完整 URL、完整 observation、raw payload、secret、文件内容或 chain-of-thought。

对应代码：

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
src/klara/prompts/thinking_summary_narrator.md
apps/web/src/components/klara/KlaraActivityDrawer.tsx
apps/web/src/types/domain.ts
```

### 3. Developer Debug

Developer Debug 是教学和工程排查区域，默认折叠。这里才显示详细链路：

```text
Developer debug · 38 events · 3 tools
```

展开后可以看到：

- LLM rounds：turn index、model、duration、input/output/total tokens、token source。
- Tools：tool name、status、duration、arguments preview、observation preview。
- Trace：event count、trace saved、event_id、created_at、event_type。
- Raw payload：只放在 Developer Debug 的 `<details>` 里。

如果 payload 里没有 token 或 duration，UI 显示 `unknown`，不编造指标。

对应代码：

```text
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/KlaraRunStatus.tsx
apps/web/src/styles/klara.css
```

## 3.1 为什么不把工具链路塞进 Thinking

工具链路很重要，但它不是用户可见 thinking。

如果顶部 thinking 展开后直接显示 `Searched web / Opened page / Answered`，会产生两个问题：

- 用户会以为这是模型的真实思考过程。
- debug 信息会抢掉回答本身的阅读路径。

所以本章的边界是：

```text
Top Thinking Trigger -> 轻入口，只告诉用户 Klara 正在/已经思考
Activity Drawer      -> 公开、可证据追溯的 activity summary
Developer Debug      -> 工程 trace、tool card、payload、metrics
```

这也是本章最重要的产品边界：公开活动可以展示，隐藏推理不展示，工程 debug 不伪装成 thinking。

## 3.2 Public Activity Item Contract

Chapter 3 新增的 activity item shape 是：

```json
{
  "id": "act_...",
  "title": "Looking up public information",
  "body": "Klara is checking external sources before answering.",
  "status": "running",
  "kind": "evidence",
  "source": "runtime_event",
  "evidence_event_ids": ["evt_..."],
  "confidence": 0.9
}
```

`kind` 可以是：

```text
orientation
evidence
tool_activity
composition
finalization
```

`source` 可以是：

```text
runtime_event
narrator_model
provider_reasoning
fallback
```

本章实际主路径使用 `runtime_event` 和 `narrator_model`。`provider_reasoning` 只是给未来 provider reasoning stream 预留，不代表现在展示 raw chain-of-thought。

## 3.3 Runtime Activity Projection

我们不改 core loop，也不改 hook 协议。runtime activity 在 API projection 层从已有 events 派生。

例子：

```text
llm_call_started
-> activity_item_upserted: "Reading the request"

tool_call_started web_search
-> activity_item_upserted: "Looking up public information"

tool_call_completed web_fetch
-> activity_item_upserted: "Source material reviewed"

answer_streaming_started
-> activity_item_upserted: "Writing the answer"
```

这类 item 只能描述公开发生过的行为，不携带 raw args、完整 URL、完整 observation 或 raw payload。

对应测试：

```text
tests/apps/api/test_run_event_projector.py
tests/apps/api/test_thinking_summary.py
```

## 3.4 Narrator Summary

Narrator model 只负责完成后的公开 activity summary：

```text
输入：完整 public run events
输出：2-5 条 activity items + fallback text
不会：参与最终答案、进入对话历史、改写 assistant message
```

它必须输出 strict JSON：

```json
{
  "text": "Klara prepared the run, checked public evidence, and wrote the final answer.",
  "items": [
    {
      "title": "Checked public evidence",
      "body": "Klara searched public sources before composing the answer.",
      "kind": "evidence",
      "evidence_event_ids": ["evt_123"],
      "confidence": 0.8
    }
  ]
}
```

校验器会拒绝或降级不可靠内容：

- item 数量必须是 2-5 条。
- title/body 不能为空。
- body 不能过长。
- `evidence_event_ids` 必须真实存在。
- 不能声称搜索、打开、读取、验证、运行、编辑或测试过不存在的动作。
- narrator 失败不影响主回答。
- narrator 不可用时只 emit `thinking_summary_completed has_summary=false`，不生成假 summary。

## 3.5 Hooks 和 Trace 仍然是 Runtime 骨架

本章的 UI 改造没有改变核心 hooks/trace 结构：

```text
KlaraLoop
-> public KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> SSE / Activity Drawer / Developer Debug
```

Hooks 的职责仍然是生命周期观察和有限插点：

```text
UserPromptSubmit -> 用户请求进入 runtime
PreToolUse       -> 单个工具执行前
PostToolUse      -> 工具 observation 生成后
Stop             -> run 完成前
```

本章明确不把 hooks 变成语义纠错器、domain guard、intent router 或搜索规则引擎。

## 3.6 为什么这是真实的

这套 Activity 不是假的“我正在深入思考”动画：

- 每个 activity item 都有 `evidence_event_ids`。
- runtime item 从真实 RunEvent 派生。
- narrator item 必须引用已有事件。
- narrator 不可用时不编造内容。
- Activity 不展示 raw chain-of-thought。
- Developer Debug 和用户可见 Activity 是两条不同路径。

这让 Klara 同时接近两类成熟产品体验：

- GPT-like collapsed `Thought for X >` 入口。
- Claude Code / Codex-like 可观察 workstream。

但 Klara 把公开 activity 和 raw debug 分开，避免把工程日志伪装成思考。

## 3.7 快速体验

启动：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

可以测试三个问题：

```text
现在上海时间几点？
```

期望：模型可以调用 `current_time`，顶部只显示 `Thinking...` / `Thought for X`，Activity Drawer 显示公开活动，Developer Debug 展示工具事件。

```text
帮我搜一下最新世界杯赛程。
```

期望：如果模型使用 web 工具，Activity 只总结公开动作；Developer Debug 才展示 `web_search` / `web_fetch` 细节。runtime 不用硬编码世界杯规则修补答案。

```text
生成一张克拉拉形象图。
```

期望：模型可以调用 `image_generate`，回答区域展示图片；Activity 和 Debug 仍然分层。

## 3.8 本章不做什么

Chapter 3 不做：

- raw chain-of-thought 展示。
- intent router。
- domain guard。
- 搜索关键词规则。
- source ranker。
- grounding verifier。
- 复杂权限系统。
- memory / context compression。

这些能力会在后续章节逐步讲，但本章必须先把 loop、hooks、trace、Activity 和 Debug 的边界立住。

## 代码索引

```text
apps/api/schemas.py
apps/api/services/run_service.py
apps/api/services/run_event_projector.py
apps/api/services/workstream_narrator.py
src/klara/prompts/thinking_summary_narrator.md
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
apps/web/src/styles/klara.css
```

## 运行和验证

后端：

```powershell
python -m pytest
```

前端：

```powershell
cd apps\web
npm test
npm run build
```

人工检查：

1. 顶部只显示 `Thinking...` 或 `Thought for X >`。
2. 点击 chevron 打开 Activity Drawer。
3. Activity Drawer 有 `Klara thinking` 和 `Agent activity`。
4. 顶部 thinking 不出现工具 debug 链路。
5. Developer Debug 默认折叠。
6. Developer Debug 展开后能看到 LLM rounds、tool cards、trace 和 raw payload。

## 下一章

Chapter 4 会讲 Harness And Config：当 loop、tools、hooks、trace、activity 和 debug 都有边界之后，下一步是把 provider、model、prompt、tools、hooks、policies 和 trace sinks 收束到一个清晰的 harness entry point。
