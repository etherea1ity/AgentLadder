# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Chapter 3 不给 loop 加业务规则。它把一次 Klara 回答拆成三层：回答前的轻量 Thinking、右侧 Activity Drawer、回答下方的 Developer Debug。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

## Thinking 放在哪里

Thinking 属于 assistant message 内部，放在最终回答正文前面。

它不是全局 loading，不是底部 debug，也不是一大块 trace 面板。运行中应该像这样：

```text
Klara · Thinking... 3.2s
我先理解了你是在问世界杯的最新进展，所以不能只靠模型记忆回答。我会先查公开来源，再把已确认赛果和待赛赛程分开整理。

最终回答开始逐步出现...
```

完成后收起成：

```text
Klara · Thought for 24.2s >
最终回答正文
Developer debug · collapsed
```

`Thought for X` 必须有真实可展示内容支撑。如果 provider reasoning、主模型公开 commentary、runtime action transcript 都没有内容，完成后不显示空的 `Thought for X`，耗时只留在 Developer Debug。

## 三条公开链路

### A. Provider Reasoning

这是 provider 或模型原生返回的公开 reasoning summary，例如 `reasoning_content`、`reasoning`、`thinking` 等字段。

Klara 会把它投影成：

```text
provider_reasoning_delta
provider_reasoning_completed
```

它只用于 UI 展示，不写进最终 assistant answer，也不进入下一轮主模型 history。没有 provider reasoning 时不伪造。

### B. Main Model Public Commentary

这是主模型自己写给用户看的公开说明，不是 hidden chain-of-thought。

第一版支持两种来源：

- provider 或 wrapper 返回结构化字段：`activity_commentary`、`public_activity`、`commentary`
- 模型同一轮同时返回 `content + tool_calls` 时，`content` 被视为公开 activity commentary，而不是最终答案

语义是：

```text
我理解了用户在问什么。
我接下来会怎么处理。
Klara 会继续做什么。
```

它会投影成：

```text
assistant_activity_delta
assistant_activity_completed
```

这条 commentary 不进入最终 answer，不进入下一轮主模型 history，也不会混进 answer chunks。

### C. Runtime Action Transcript

这是 Klara runtime 真实发生过的动作摘要。它不是 Thinking 本身，但应该在 Activity Drawer 里作为 Agent activity 展示。

示例：

```text
web_search · 8 results · fifa.com · reuters.com
web_fetch · FIFA official schedule · fifa.com · 2300 chars
image_generate · 1 asset
current_time · completed
```

公开 transcript 只展示安全摘要：工具名、状态、数量、来源标题、域名、短 preview。完整 URL、完整 query、完整参数、完整 observation、raw payload 留给 Developer Debug。

## 三层界面

### 1. Thinking Trigger

主路径只有一行轻量入口：

```text
active:    Klara · Thinking... 1.2s
complete:  Klara · Thought for 24.2s >
```

运行中如果有主模型公开 commentary，就显示最新一条短说明。完成后只显示 `Thought for X` 入口，不在主对话里铺工具列表、event list 或 debug trace。

交互上，左侧是 mini Klara icon + label，右侧 chevron 是唯一打开 Activity Drawer 的按钮。点击文字本身不展开。

### 2. Activity Drawer

Drawer 是详情，不是主实时体验。它展示三段：

```text
Model thinking  -> provider_reasoning_delta
Klara activity  -> assistant_activity_delta
Agent activity  -> runtime action transcript
```

没有 provider reasoning 就隐藏 `Model thinking`。没有主模型 commentary 时，`Klara activity` 显示轻量 empty state。没有 runtime action 时隐藏 `Agent activity`。

Drawer 里不展示 raw chain-of-thought、raw tool arguments、full URL、raw observation、raw payload。

### 3. Developer Debug

Developer Debug 默认折叠，只给开发和教学看：

- LLM rounds：turn、model、duration、input/output/total tokens、token source
- Tools：tool name、status、duration、arguments preview、observation preview
- Activity facts：结构化 facts、evidence ids、safe metrics
- Trace：event id、created_at、event_type、raw payload

Developer Debug 可以显示 raw payload，因为它是开发者区域；Thinking Trigger 和 Activity Drawer 不显示 raw trace、tool cards 或 event list。

## 为什么这版不再做假 Thinking

之前的问题是：

- 只有 timer，也会显示 `Thought for X`
- Activity Drawer 可能打开后是空的
- runtime event 被包装成固定句子，例如 "Reading request" 或 "Writing answer"
- provider reasoning 有类型但不一定有真实内容
- 最终答案一次性出现，看起来不像正在输出

现在的规则是：

- 有 A/B/C 任意内容时，才允许完成后显示 `Thought for X`
- 主模型公开 commentary 是 Thinking 的主来源之一
- runtime action transcript 只做紧凑事实摘要，不伪装成模型思考
- 最终 answer 可以分块输出，但 Thinking/Activity 永远不混进 answer

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

验收时看四件事：

1. assistant 消息内部先出现 `Thinking...`。
2. 如果模型输出了 public commentary，它会显示在回答前。
3. 完成后没有 A/B/C 内容时，不显示空的 `Thought for X`。
4. Developer Debug 才显示 tools、raw payload 和完整 trace。

## 本章不做什么

Chapter 3 不展示 raw chain-of-thought，不做 intent router，不做 domain guard，不做搜索关键词规则，不做 source ranker，不做 grounding verifier，不做 memory/context compression。

这些放在后续章节。本章只把 Thinking、Activity、Debug 的边界立住。
