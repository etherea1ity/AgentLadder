# 第 12 章：受控 Agentic RAG

语言：中文 | [English](./ch12-controlled-agentic-rag.en.md)

> 本章把已有的证据数据结构接入真实 Agent 最终回答路径。Chapter 11 的通用文档知识库仍按范围延期；本章只处理网页研究产生的证据，不能用来宣称通用 RAG 已完成。

![证据控制流程](../assets/ch12-13-evidence-flow.svg)

## 问题

搜索结果并不是答案。搜索摘要可能截断、过期或与页面正文不一致；模型即使已经抓取页面，也可能引用不存在的 source id、遗漏必要引用，或者把矛盾证据写成确定事实。原有 `EvidenceController` 只在 Lab A fixture 中执行，因此不能约束 API 真实运行。

本章的产品目标是：只要一次运行被判定为需要网页研究，最终文本就必须先经过 claim-level 证据提交与运行时验证。一个 required claim 没有通过时，系统继续修正或明确拒答，而不是放行一段看起来合理的散文。

## 机制一：搜索候选与证据分离

`web_search` 只产生带 `must_fetch_before_citing=true` 的候选卡。它的 snippet 不进入 `EvidencePack`。只有 `web_fetch` 成功读取公开页面正文后，`EvidenceLedger` 才建立 `SourceRecord`，并记录最终 URL、抓取时间、完整受限正文、SHA-256、质量、状态和 limitations。

```text
web_search candidate
  -> web_fetch
  -> SourceRecord(content, content_hash, fetched_at, status)
  -> EvidencePack
```

因此，把 `cand-*` 当作 `source_id` 会在真实运行时得到 dangling-source 错误；仅搜索未抓取也无法通过最终回答控制。

## 机制二：结构化回答交接

`evidence_submit` 是无副作用工具。模型提交 proposed final text、material claims、claim/source links、semantic judgment、逐条原文 witness 和 citations。它不直接发布答案，只把结构化对象交给 `EvidenceRuntimeController`。

工具的完整结果只在本次模型回路可见。公开 trace 使用独立 `public_content`，只显示 claim/link/citation 数量以及是否声明 abstention，不复制 final text 或 support note。

<details>
<summary>为什么不解析 Markdown 链接来猜 claim？</summary>

Markdown 只能说明模型写了一个链接，不能说明链接支持哪条 claim，也不能表达 contradicted、insufficient、required 或 source status。显式 join key 才能稳定回放和评分。

</details>

## 机制三：确定性最终答案门

验证器按以下顺序失败关闭：

1. claim、link、citation 和 source id 必须存在且唯一；
2. EvidencePack 拒绝重复 source id、规范化 URL 和相同内容 hash；
3. supported/contradicted link 的 `support_note` 必须是抓取正文中的精确短 witness；
4. required claim 只有在 admissible source、supported link 和 citation 同时存在时才能通过；
5. contradicted、stale、irrelevant、insufficient 或 dangling 会阻止事实答案；
6. 证据确实不足时允许显式 `abstain=true`，但必须提供公开的拒答原因和最终文本。

核心回路支持 `FinalAnswerDecision.replacement_content`。验证通过后，发布的是 `evidence_submit.final_text` 加由运行时根据已抓取 URL 生成的 Sources 列表；模型随后返回的未受控草稿不会离开回路。

## 真实源码与状态变化

- `src/klara/services/evidence/runtime.py`：真实 LoopController、EvidencePack 构建、witness 检查、引用渲染和 abstention。
- `src/klara/tools/builtin/evidence_submit/`：模型可见结构化交接合同与 trace-safe 投影。
- `src/klara/core/loop.py`：聚合多个控制器，并使用经过控制器批准的 replacement content。
- `src/klara/services/web/research.py`：抓取正文 hash、状态、limitations 与 provenance。
- `apps/api/services/run_event_projector.py`：只公开验证状态、claim judgment 和 join id。
- `apps/web/src/components/ChatWorkspace.tsx`：显示 Evidence verified、blocked 或 evidence-limited，不显示隐藏推理。

一次成功运行的状态序列是：

```text
web_research.started
-> evidence.candidate_recorded
-> evidence.source_recorded
-> evidence.answer_submitted
-> evidence.verification_completed(allowed=true)
-> final_answer.allowed
```

## 实验与复现

```powershell
$env:PYTHONPATH = "src"
python -m klara.eval.chapter12_13_cli `
  --json-out docs/reports/product/ch12-13-evidence-runtime.json `
  --markdown-out docs/reports/product/ch12-13-evidence-runtime.md `
  --markdown-en-out docs/reports/product/ch12-13-evidence-runtime.en.md
pytest -q tests/klara/services/evidence tests/klara/eval/test_gate.py
```

确定性关键金标要求 Citation Precision、Citation Recall、Contradiction Recall 和 Abstention Accuracy 全部为 `1.0`。真实回路测试另行覆盖候选冒充来源、伪造 witness、stale、irrelevant、contradicted、duplicate 和显式拒答。

门禁还执行一次 `https://example.com/` 的受限在线抓取探针。它只验证当前网络路径与安全抓取器，不参与确定性准确率；外部网络不可用时保留 `unavailable`，不能改写金标结果。

## 局限与下一步

确定性 fixture 的满分不是开放域准确率。语义 judgment 仍由回答模型或未来 judge 产生，运行时只验证来源、join、状态、引用与原文 witness，不把字符串相似度伪装成事实判断。第 13 章继续冻结 bounded research、source readiness、冲突和 UI 呈现；正式文档 RAG 仍未完成。
