# Chapter 4：Harness 与 Config

语言：中文 | [English](./ch04-harness-and-config.en.md)

上一章：[Chapter 3：Hooks 与 Trace](./ch03-hooks-and-trace.md)

下一章：[Chapter 5：Todo Planning](../skills/roadmap.md#chapter-5---todo-planning)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 在 loop 启动前由一个 harness 校验模型能力，并把 persona、工具、hooks、trace、用户上下文和预算冻结成可复现的运行快照。

![Klara Chapter 4 Harness 与 Config](../assets/ch04-harness-config.svg)

| 启动信号 | Harness 做什么 |
| --- | --- |
| 模型满足 profile 要求 | 生成 `profile_sha256`，再构造 loop |
| 模型缺少 tools/thinking 等能力 | 在第一次 LLM 请求前失败 |
| profile 要求不存在的工具 | 在启动前失败 |
| API 或 CLI 创建 run | 都经过同一个 `KlaraHarness` |

## 快速体验

无需调用真实模型，先打印安全运行快照：

```powershell
$env:PYTHONPATH = "src;."
python -m klara.app.cli --profile-only
```

你会看到模型、能力 profile、可见工具、hooks、loop 预算、persona hash 和 `profile_sha256`；看不到 API key、provider URL 或 `.env` 内容。

再启动网页：

```powershell
.\scripts\dev.ps1
```

打开模型选择器。每个模型的 Tools、JSON、Vision、Thinking 能力来自 `config/models.toml`，不是前端硬编码。

## 真实问题：为什么“有一个 Harness 类”仍然不够

此前直接单元测试会使用 `KlaraHarness`，但真实 API 在 `RunService` 里再次手工创建 `KlaraLoop`。两条路径可以悄悄产生不同工具、不同 hook、不同 prompt 和不同预算；配置文件存在，也无法证明某个 run 实际用了哪一份配置。

Chapter 4 的修复不是再加一层包装，而是建立唯一产品组装边界，并把组装结果记录为证据。

## 机制一：能力 profile 描述运行需要什么

`config/runtime.toml` 中的 `runtime.capability_profiles.agent` 声明必需模型能力、可见工具、hook 列表与 trace sink。loader 把它解析为冻结的 `CapabilityProfile`，并拒绝未知能力、重复项、错误 sink 和不存在的默认 profile。

<details>
<summary>查看真实配置与类型</summary>

```text
config/runtime.toml
src/klara/infra/config/runtime.py
src/klara/infra/config/loader.py
```

`LoopPolicy` 仍然属于 core 的纯预算对象；加载和环境变量覆盖留在 infra，core 不读取 TOML 或 `.env`。

</details>

## 机制二：Harness 在执行前协商模型与工具能力

`KlaraHarness` 解析 `provider/model`，查找 `ProviderModel` 的 Tools、JSON、Vision、Thinking 标记，再与 capability profile 比较。配置了不存在的工具或不支持的模型能力时，构造 harness 就失败，LLM 调用次数保持为零。

<details>
<summary>查看前置拒绝测试</summary>

```text
src/klara/app/harness.py
tests/klara/app/test_harness.py
tests/klara/infra/config/test_loader.py
```

`update_activity` 是 core 注入的内部公开活动工具，harness 会把它与 registry 业务工具分开核验，但仍保留在模型可见快照里。

</details>

## 机制三：运行快照可复现但不泄露连接信息

`KlaraRunProfile` 是 frozen dataclass。它包含影响行为的公开配置，并以稳定 JSON 计算 SHA-256。相同输入得到相同 hash；persona 只保存内容 hash；API key 名、值、base URL 和 provider 私有字段不会进入快照。

```text
config + persona + tools + hooks + context + budgets
-> stable public JSON
-> profile_sha256
-> run_profile_frozen event
```

Developer Debug 可以看到这条公开事件，从而回答“这次 run 到底怎样组装”，但不能借此读取凭据。

## 机制四：API 与 CLI 共用同一个组装入口

`RunService` 仍负责 session、SSE、取消和持久化，但不再直接构造 `KlaraLoop`。它把 API 选择的模型、thinking、浏览器时区和历史消息交给 harness。CLI 只负责参数和输出，也通过 harness。

<details>
<summary>查看产品入口</summary>

```text
apps/api/services/run_service.py
src/klara/app/cli.py
tests/klara/architecture/test_product_entrypoints.py
```

架构测试直接禁止这两个产品入口出现 `KlaraLoop(`，防止以后无意绕过 harness。

</details>

## 运行与验证

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.chapter04_cli `
  --repository-root . `
  --json-out docs/reports/product/ch04-harness-config.json `
  --markdown-out docs/reports/product/ch04-harness-config.md `
  --markdown-en-out docs/reports/product/ch04-harness-config.en.md
python -m pytest -q
Push-Location apps/web
npm test
npm run build
Pop-Location
```

机器门禁必须 `11/11` 通过，包括统一入口、hash 校验、模型/工具能力、trace、secret scan 与 stage manifest。

## 小实验

1. 把 agent profile 的 `required_model_capabilities` 改成 `vision`，再选择不支持视觉的模型，观察启动前拒绝。
2. 连续运行两次 `--profile-only`，确认 `profile_sha256` 完全相同。
3. 修改 persona 一个字符，确认 persona hash 和 profile hash 同时变化。

## 下一章预告

Chapter 4 只保证“一次 run 从同一份可验证配置出发”。Chapter 5 会加入 Todo Planning，让长任务的目标、步骤和变更成为正式状态，并在 trace 与 UI 中可见。
