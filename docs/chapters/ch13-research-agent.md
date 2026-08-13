# 第 13 章：Research Agent

语言：中文 | [English](./ch13-research-agent.en.md)

> 第 13 章把第 12 章的证据门放进 bounded web research 状态机。目标是可观察、可停止、可复现的研究过程，不是无边界爬虫或黑盒 `deep_search` 工具。

![Research Agent 证据流](../assets/ch12-13-evidence-flow.svg)

## 问题

一个研究 Agent 不只是“能调用搜索”。它必须知道什么时候需要网页、何时搜索摘要仍只是线索、抓取了多少独立来源、来源质量是否足够、预算何时耗尽，以及最终回答是否逐 claim 通过证据控制。如果这些状态只存在于模型散文里，用户看不到真正进度，失败也无法回放。

## 机制一：运行时拥有的研究状态机

`WebResearchController` 在 run start 对问题进行稳定/时效性分类，建立 quick、deep 或 off 模式。quick 的默认上限为 3 次搜索、5 次抓取和至少 1 个合格来源；deep 的默认上限为 8 次搜索、16 次抓取、至少 3 个合格来源和 2 个独立域名。

```text
web_required
-> searching
-> fetching
-> verifying
-> ready | need_more_search | need_more_fetch | budget_exhausted
```

系统 prompt 只注入紧凑状态、缺口和下一步提示。旧的完整 `web_fetch` observation 会压缩为保留 source id 的摘要，避免长页面正文无限占用上下文。搜索、抓取和最终回答仍由同一个 `KlaraLoop` 排程，不创建隐藏的第二个 Agent loop。

## 机制二：来源准备度与冲突

`EvidenceLedger` 严格分离 candidates 和 fetched sources。准备度检查至少需要可读且与请求相关的抓取正文；deep research 还要求多个独立域名。低质量、无相关词、重复 URL 或重复正文都不能伪装成独立证据。

冲突不是简单多数投票。模型必须在 `evidence_submit` 中为 claim/source 对声明 `supported | contradicted | insufficient` 并给出正文 witness。任何 contradicted required claim 都不能以确定事实发布；系统可以继续检索、改写为有边界的结论，或显式 abstain。

## 机制三：产品可观察性

公开事件包括研究启动、候选记录、来源记录、准备度、结构化回答提交和验证结果。API 投影会删除 final draft 和 witness 正文，只保留计数、状态、claim id、judgment、source id 与 citation key。

聊天界面的 Evidence 状态条显示：

- Gathering evidence：来源或独立域名仍不足；
- Sources ready：研究准备度通过但 claim gate 尚未完成；
- Evidence verified：required claims 已通过；
- Evidence blocked：验证未通过；
- Evidence-limited answer：系统明确拒答或保留不确定性。

这不是伪造的“思考动画”。状态只来自持久化的公开事件，屏幕阅读器通过 `aria-live=polite` 接收变化。

<details>
<summary>为什么预算耗尽不等于事实正确？</summary>

预算耗尽只说明没有更多可执行网络动作。第 12 章的 evidence gate 仍要求逐 claim 验证；没有足够证据时必须提交 explicit abstention，不能因为没钱或没调用次数就放行未经支持的断言。

</details>

## 真实源码与运行实验

- `src/klara/services/web/research.py`：模式、预算、EvidenceLedger、准备度与 compaction。
- `src/klara/tools/builtin/web_search/`：候选卡、provider 限制和 freshness 是否真正 enforced。
- `src/klara/tools/builtin/web_fetch/`：SSRF 安全边界、受限正文、质量信号和抓取时间。
- `src/klara/services/evidence/runtime.py`：最终 claim gate。
- `apps/web/src/components/ChatWorkspace.tsx`：来源/claim 状态的正常用户界面。

```powershell
$env:PYTHONPATH = "src"
pytest -q tests/klara/services/test_web_research.py tests/klara/services/evidence
python -m klara.eval.chapter12_13_cli `
  --json-out docs/reports/product/ch12-13-evidence-runtime.json `
  --markdown-out docs/reports/product/ch12-13-evidence-runtime.md `
  --markdown-en-out docs/reports/product/ch12-13-evidence-runtime.en.md
```

真实回路 fixture 按 `web_fetch -> evidence_submit -> final` 顺序执行，最后确认发布文本来自已验证 submission 而不是模型之后随意生成的草稿。在线 smoke 只访问一个公开页面、最多 2000 字符、12 秒超时。

## 局限与下一步

当前默认 no-key 搜索 provider 不保证 freshness hint，一些 JS 页面也无法抽取；这些 limitation 会进入 observation，而不是被隐藏。公开页面 smoke 只能证明当前网络和抓取器可用。开放域研究质量要在 Agent Product Freeze 阶段用固定回答模型、隐藏集、真实问题和人工盲审继续测量。

下一阶段是 Permission Engine。它将把网络域名、资源、actor、tenant、风险和 side effect 作为显式授权条件；本章的网络工具不能代替完整权限系统。
