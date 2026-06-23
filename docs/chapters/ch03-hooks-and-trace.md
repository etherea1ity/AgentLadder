# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Chapter 3 不给 loop 加业务规则，而是把 Klara 的一次回答拆成三层：用户可见的 Thinking、可展开的 Activity Drawer、开发者专用的 Developer Debug。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

## Thinking 放在哪里

Thinking 属于 assistant message 内部，放在最终回答正文前面。

它不是页面顶部的全局状态，不是底部 debug 面板，也不是一个运行时 trace 大框。

运行中应该像这样：

```text
Klara · Thinking... 3.2s
我先理解了你是在问世界杯的最新进展，所以需要查当前来源，而不是只靠模型记忆。

最终回答开始逐步出现……
```

完成后应该像这样：

```text
Klara · Thought for 24.2s >
最终回答正文
Developer debug · collapsed
```

`Thought for X` 必须有真实可展示内容支撑：provider/model reasoning、Klara preamble，或 narrator 生成的 Klara activity。三者都没有时，不显示空的 `Thought for X`，运行耗时只留在 Developer Debug。

## 三层界面

### 1. Thinking Trigger

主路径只有一行轻量入口：

```text
active:    Klara · Thinking... 1.2s
complete:  Klara · Thought for 24.2s >
```

运行中如果 `thinking_preamble_delta` 已经返回，就在这一行下面显示一条 compact preamble。它只说明 Klara 公开理解到的用户目标和高层处理方向，不回答问题，不展示工具链路。

交互上，左侧是 mini Klara icon + label，右侧 chevron 是独立按钮。点击文字或 preamble 不展开，只有 chevron 打开 Activity Drawer。

### 2. Activity Drawer

Drawer 是详情，不是主实时体验。它可以展示三类内容：

```text
Klara preamble   -> thinking_preamble_delta.text
Model thinking   -> provider_reasoning summary；没有就隐藏
Klara activity   -> narrator_model 基于 activity facts 生成的公开活动摘要
```

这里的“真实 thinking”不是 raw chain-of-thought：

- `Model thinking` 来自 provider/model 返回的公开 reasoning summary，有才展示，没有不伪造。
- `Klara activity` 来自 `activity_fact_recorded` + narrator model。runtime 只记录结构化事实，narrator 才写用户可读的公开 activity。
- narrator 不可用、JSON 错误或校验失败时，不生成模板句子，只在 Developer Debug 留诊断事件。

### 3. Developer Debug

Developer Debug 默认折叠，只给开发和教学看：

- LLM rounds：turn、model、duration、input/output/total tokens、token source。
- Tools：tool name、status、duration、arguments preview、observation preview。
- Activity facts：结构化 facts、request preview、evidence ids。
- Narrator diagnostics：started、completed、rejected、failed。
- Trace：event id、created_at、event_type、raw payload。

Developer Debug 可以显示 raw payload，因为它是开发者区域；Thinking Trigger 和 Activity Drawer 不显示 raw trace、tool cards 或 event list。

## 两条真实来源

### A. Model Thinking / Provider Reasoning

Provider 如果返回 `reasoning_content`、`reasoning`、`thinking` 等公开字段，Klara 会投影成：

```text
provider_reasoning_delta
provider_reasoning_completed
```

它只用于 UI 展示，不写进 assistant message，也不会进入下一轮主模型上下文。

### B. Klara Activity / Agent Workstream

Runtime 只产生 fact，不直接写用户可见文案：

```json
{
  "id": "fact_evt_...",
  "kind": "request_orientation",
  "status": "completed",
  "source_event_type": "thinking_summary_started",
  "evidence_event_ids": ["evt_..."],
  "request": {
    "preview": "用户请求的脱敏短摘要",
    "language": "zh"
  }
}
```

工具、搜索、网页读取、图片生成、错误也会形成各自的 fact。fact 不能包含 `title` / `body`，不能暴露完整 URL、raw arguments、raw observation、secret 或 hidden reasoning。

narrator 只根据 facts 输出公开 activity item：

```json
{
  "title": "理解请求目标",
  "body": "Klara 先识别了你想整理的主题和回答方向。",
  "kind": "orientation",
  "source": "narrator_model",
  "evidence_fact_ids": ["fact_evt_..."],
  "evidence_event_ids": ["evt_..."],
  "confidence": 0.8
}
```

如果 item 声称搜索、读取、验证、生成图片、编辑或测试，必须有对应 fact 支撑。

## 为什么之前像假的

之前的问题是：

- 只有 timer，也会显示 `Thought for X`。
- `provider_reasoning_delta` 有类型但没有真实 emitter。
- narrator 没内容时，前端还能打开空 drawer。
- runtime event 被直接包装成 “Reading request / Writing answer” 这类模板 activity。
- active 阶段没有 assistant message 内部的 live preamble。
- `answer_delta` 一次性发送完整 final text，看起来不像回答正在出现。

现在的规则是：

- 运行中可以显示 `Thinking...`，并尽快尝试生成一条 live preamble。
- 完成后只有在有 preamble、provider reasoning 或 narrator activity 时，才显示 `Thought for X`。
- 最终答案会分块发出，但 thinking/preamble/activity 不会混进 answer chunks。

## 快速体验

启动：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

可以试：

```text
现在上海时间几点？
帮我搜一下最新世界杯赛程
生成一张克拉拉形象图
```

验收时看三件事：

1. assistant 消息内部先出现 `Thinking...`，有 preamble 时显示一条短说明。
2. 完成后没有内容支撑时，不显示空的 `Thought for X`。
3. Developer Debug 才显示 tools、facts、narrator diagnostics、raw payload 和 metrics。

## 本章不做什么

Chapter 3 不展示 raw chain-of-thought，不做 intent router，不做 domain guard，不做搜索关键词规则，不做 source ranker，不做 grounding verifier，不做 memory/context compression。

这些放在后续章节。本章只把 Thinking、Activity、Debug 的边界立住。
