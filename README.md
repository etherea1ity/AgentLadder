# Chapter 3: Hooks and Trace

语言：中文 | [English](./README.en.md)

上一章：[Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](./docs/skills/roadmap.md)

完整章节：[docs/chapters/ch03-hooks-and-trace.md](./docs/chapters/ch03-hooks-and-trace.md)

算法扩展：[证据控制、蒸馏、MoE 与 FP16/FP4 实验套件](./docs/labs/algorithm-suite.md)

最终云端报告：[Algorithm Suite Freeze](./docs/reports/algorithm/algorithm-suite-freeze.md)

---

## 一句话看懂本章

Klara 不把一次回答藏成黑盒：loop 仍然只负责模型和工具，但每个生命周期点都会发出事件，hooks、JSONL trace、前端 Thinking、右侧活动栏和 Developer Debug 都从同一条 public event stream 投影出来。

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| 看到什么 | Klara 做什么 |
| --- | --- |
| `llm.started` | 记录本轮模型输入边界：消息数量、role 分布、prompt hash、工具 schema |
| `llm.completed` | 记录模型输出边界：正文、工具、公开 thinking、provider reasoning |
| `tool.*` | 记录真实工具动作、耗时、错误和安全 observation 摘要 |
| Thinking | 显示主模型公开过程说明或 provider reasoning，不显示假的空 Thought |
| Developer Debug | 展示工程 trace、tokens、duration、payload，用来教学和排查 |

## 快速体验

启动：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

试一个无工具问题：

```text
你好
```

再试一个工具问题：

```text
现在上海时间几点？
```

再试一个需要当前信息的问题：

```text
今天有什么最新新闻？
```

你应该观察三件事：

1. Thinking 和最终答案是分开的。
2. 工具调用和失败会进入 Developer Debug。
3. `llm.started.input_profile` 和 `llm.completed.response_profile` 能帮助判断每轮 LLM 到底看到了什么、返回了什么。

## 本章改了什么

Chapter 2 的核心 loop 不变：

```text
model tool_calls -> runtime executes tools -> observations return to model
```

Chapter 3 增加可观察性：

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> Thinking / Activity / Developer Debug
```

这不是 UI 装饰，而是一条稳定事件契约。它让我们能解释：

- 哪一轮 LLM 调用了哪些工具
- 哪个工具失败了
- token 和 latency 花在哪里
- 模型是否真的返回了正文
- Thinking 是模型公开 commentary、provider reasoning，还是 runtime 动作 transcript

## 关键源码

```text
src/klara/core/loop.py
src/klara/core/hooks.py
src/klara/core/events.py
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
```

## 验证

```powershell
python -m pytest tests\klara\core\test_loop.py tests\apps\api\test_run_event_projector.py -q
python -m pytest
```

当前 trace profile 改造验证结果：

```text
168 passed
```

下一章会讲 Harness And Config：一次 Klara run 在进入 loop 前如何组装模型、provider、persona、工具、hooks 和 trace sink。
