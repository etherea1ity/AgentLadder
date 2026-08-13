# Chapter 8：错误恢复与 Fallback

语言：中文 | [English](./ch08-error-recovery-and-fallback.en.md)

上一章：[Chapter 7：上下文压缩](./ch07-context-compression.md)

下一章：[Chapter 9：Skills / 程序性记忆](../skills/roadmap.md#chapter-9---skills--procedural-memory)

路线图：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话理解本章

Klara 会先给模型错误分类，只对瞬态供应商故障做有界退避重试；遇到上下文超限先压缩一次；发生模型切换则明确记录 primary 到 fallback 的路线，同时绝不公开供应商响应正文。

![Klara Chapter 8 Error Recovery](../assets/ch08-error-recovery.svg)

| 故障 | 运行时动作 |
| --- | --- |
| 超时、限流、传输故障或 5xx | 在冻结的次数预算内重试同一个候选模型 |
| Prompt 超过供应商上下文窗口 | 执行 `PreCompact`，收紧 transcript 预算，重建系统提示词并重试一次 |
| 候选模型仍不可用 | 进入配置中的下一个 fallback，同时记录两个模型引用 |
| 鉴权失败或普通请求被拒绝 | 使用类型化安全错误立即失败 |
| 工具抛异常或工具未知 | 返回失败的模型可见 observation，在有界循环内继续 |

## 快速体验

启动本地产品：

```powershell
.\scripts\dev.ps1
```

当 primary 失败而 fallback 成功时，聊天区显示 `Fallback active · primary → fallback`。Prompt 恢复时显示 `Prompt recovered · context compacted`。开发 trace 保留有序的尝试和错误码，而用户对话只得到答案或简短、安全的失败说明。

## 为什么 `try/except` 不是恢复策略

通用重试可能重复鉴权错误、再次发送已经过大的 prompt、隐藏模型切换，甚至把供应商响应正文泄露给 UI 事件。本章把责任分成三层：

```text
OpenAI-compatible adapter -> 分类单个供应商候选
Routed client             -> 选择并公开候选顺序
Core loop                 -> 恢复上下文并保持生命周期顺序
```

`ModelCallError` 定义在 core 中，因此循环可以恢复而不依赖供应商基础设施。它的公开字段只有 `code`、`retryable`、`status_code` 和 trace-safe runtime events；异常 message 不属于公开数据。

## 机制一：只重试瞬态故障

HTTP 408、429、500、502、503、504 可以重试；传输错误和超时可以重试。鉴权失败、普通请求拒绝、无效响应和上下文超限不会在 HTTP adapter 内重试。

冻结策略公开尝试次数、基础延迟、最大延迟和可选超时。默认不限制供应商读取时间，因为 thinking 调用可能较长；运维可以通过 `KLARA_PROVIDER_TIMEOUT_SECONDS` 设置边界，无需改源码。

<details>
<summary>查看供应商策略与故障测试</summary>

```text
config/runtime.toml
src/klara/infra/config/runtime.py
src/klara/infra/llm/openai_compatible.py
tests/klara/infra/llm/test_openai_compatible.py
```

测试注入 HTTP 错误，把 sleep 替换为记录器，并断言严格的事件顺序。供应商正文带有私有 marker，测试要求它不出现在事件和错误字符串中。

</details>

## 机制二：上下文超限必须回到上下文所有者

遇到 `context_length_exceeded` 时，router 不会立刻切模型。Core 先发出 `model_call.failed`，开始 prompt recovery，调用已有的 `PreCompact` hook，再让支持恢复的 controller 把 transcript 预算收紧到 70%。

```text
llm.started
-> model_call.failed
-> prompt_recovery.started
-> pre_compact.started / completed
-> context.prompt_recovery_applied
-> prompt_recovery.completed
-> llm.started
```

第二次请求会重新构造系统提示词，确保新的私有 session summary 真正进入模型上下文。恢复次数由 `max_prompt_recovery_attempts` 限制，本章默认一次。

## 机制三：Fallback 是可观察路线，不是秘密

`config/models.toml` 的 profile 已定义 primary 与有序 fallbacks。`RoutedLlmClient` 现在发出 candidate start/failure/completion 和 `model_route.fallback_started`。`ModelResponse.model_used` 记录实际模型，`llm.completed` 同时保存 `requested_model` 与 `model`。

<details>
<summary>查看路由、API 投影和 UI</summary>

```text
src/klara/infra/llm/routed_client.py
apps/api/services/run_event_projector.py
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/ProviderRecoveryStatus.test.tsx
```

恢复 banner 只读取持久化 SSE 事件，不从自然语言猜测供应商状态；如果没有发生恢复，它不会渲染任何内容。

</details>

## 机制四：公开失败证据有硬边界

供应商尝试事件只包含 provider id、模型引用、尝试编号、错误码、是否可重试、状态码和延迟。它们绝不包含响应正文、请求 prompt、凭据、header 或异常字符串。API 把类型化错误映射为少量用户安全文案，同时保留错误码供支持与评测使用。

工具失败继续沿用 Chapter 2 observation contract：assistant 收到 `ToolResult(ok=False)` 并可以解释限制。失败不会被伪装成成功，一个坏工具也不会在模型有机会回答之前直接让循环崩溃。

## 运行与验证

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.chapter08_cli `
  --repository-root . `
  --json-out docs/reports/product/ch08-provider-recovery.json `
  --markdown-out docs/reports/product/ch08-provider-recovery.md `
  --markdown-en-out docs/reports/product/ch08-provider-recovery.en.md
python -m pytest -q
Push-Location apps/web
npm test
npm run build
Pop-Location
```

确定性门禁会注入一次 503 后成功、primary 失败后 fallback、一次上下文拒绝后压缩，以及一个未知工具；全部 18 项 contract 都不调用付费供应商。

## 小实验

1. 把 retry attempts 改为 1，确认不再出现 `provider.retry_scheduled`。
2. 注入 HTTP 401，确认 adapter 不 sleep，也不重新选择同一候选模型。
3. 把 prompt recovery attempts 设为 0，确认上下文超限以类型化安全失败结束。
4. 增加第二个 fallback，确认 candidate index 和最终实际模型仍保持有序。

## 本章边界与下一章

本章提供确定性恢复机制，不包含供应商健康评分、生产事故响应、跨进程 circuit breaker 或学习式路由。Chapter 9 将加入渐进披露的程序性 Skills；生产级队列与多 worker 恢复位于后续路线图。
