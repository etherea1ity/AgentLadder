# Agent 产品评测与冻结前门禁

语言：中文 | [English](./agent-product-benchmarks.en.md)

上一章：[Chapter 18：生产运行时与评测桥](./ch18-production-runtime-and-eval-bridge.md)

下一阶段：Agent Product Freeze（当前未获准）

---

## 本章一句话

这一阶段把当前 Agent 的真实 Harness、安全状态、公开 Memory/Agent benchmark 来源和竞品实现固定为可复现契约；本地链路已经通过，但真实候选、独立裁判、盲人评和官方可比成绩还未完成，因此本章总门禁保持 FAIL，模型训练继续禁止。

## 1. KlaraBench v2

`tests/fixtures/behavior/agent_behavior_cases.v2.json` 固定 11 个用例和 41 个重复观测，覆盖中英混合回答、任务、Skill、调度、Memory、最新纠正、权限审批、租户隔离、Memory 注入、破坏性范围与歧义停止。

运行器不会直接填写“成功”。它为每个观测创建隔离的 SQLite 任务、调度、Memory 与 Permission 状态，调用真实 `KlaraHarness` 和正式工具适配器，再从 transcript、持久化状态与公开事件推导 action、state 和 invariant。脚本模型只重放公开参考答案与工具参数，用于校准用例与运行时是否一致。

校准结果为 `41/41`。这不是当前 DeepSeek/Qwen/Klara 学习模型的能力分数，也没有自动填写 independent judge 或 human label。

## 2. 运行时发现并修复的问题

真实校准最初发现“我的定时任务状态”和“我的 release report 偏好”在成功读取本地工具后，仍被 Web Research Controller 当成外部事实，强制要求网页证据并停在 `max_turns`。

修复后，Web 分类会结合本次实际可见工具，把明确的所有者任务、调度、Memory 与 Skill 元数据请求路由到本地状态；“最新 NBA 赛程”等公开外部请求仍会进入 Web 证据门禁。该行为有专门回归测试。

## 3. Memory 公共基准

LoCoMo 使用官方提交和数据哈希，固定 official scored categories 1–4，每个 conversation 取 10 题，共 100 题，所有系统共享语料、问题与 `top_k=5`。当前 Klara hybrid 的 evidence Recall@5 为 `0.630588`，Hit@5 为 `0.68`，MRR 为 `0.439`。这只说明检索到 gold evidence ID，不是答案正确率。

LongMemEval 使用官方 cleaned oracle 的 500 题数据，按 question ID 哈希固定 60 题，验证 answer session、内容、答案与 6 类能力标签。Oracle 已只保留答案相关 session，因此该结果不能评价检索质量或回答准确率。

MemoryAgentBench 固定官方 dataset revision，验证 Accurate Retrieval、Test-Time Learning、Long-Range Understanding、Conflict Resolution 四个 split，共 146 行、3671 个问题。当前仅通过 schema、来源和问答对齐契约，没有运行增量 Memory Agent 回答模型。

## 4. Mem0、MEM1 与 BEAM

Mem0、MEM1、BEAM 均固定到 manifest 中的官方提交：

- Mem0 官方 memory-benchmarks 需要 Mem0 OSS/Qdrant 或 Cloud，并且 extraction、embedding、answerer、judge 都会改变成绩。
- MEM1 是 Qwen2.5-7B 的学习型 constant-memory Agent，需要 vLLM、GPU retriever、官方 rollout 与 eval；它不是可直接替换的本地检索函数。
- BEAM 公开 100 个长对话和 2000 个验证问题，长度覆盖 128K 至 10M；正式运行需要下载带哈希的官方数据，并固定能力子集、回答模型与裁判。

所以本地的 `semantic_recency` 只称作本地消融，不再冒充 Mem0；竞品均为 `not_executed/not_claimed`。

## 5. AgentBench 与 τ²-bench

AgentBench 固定 Apache-2.0 官方提交和九类任务定义；低资源配置包含 DBBench 和 OS，并验证了 DBBench dev/standard 的 60/300 行。τ²-bench 固定 MIT 官方提交，验证 mock、airline、retail、telecom、banking_knowledge 共 2556 个唯一任务及核心标签。

这些只是来源与任务契约。正式分数必须运行官方环境、工具与 grader，并冻结 Agent 模型、τ² user simulator、最大交互轮数和预算；当前没有声称成绩。

## 6. 付费与人评边界

当前 stage manifest 的 `paid_api_usd` 为 `0`。候选实跑 CLI 在任何网络调用前检查该字段并拒绝零预算，同时要求显式输入模型的 input/output token 单价。候选全覆盖完成后才会生成盲评 queue；queue 不含 candidate slot，private key 单独保存，并且同一答案的不同 repetition 仍有唯一 pair ID。

真实候选报告会保留全部公开 observation，但不会预填 reference success：脚本化校准不得冒充真实 GPT/Codex 参考运行。`behavior_labels_cli` 只接收与候选报告哈希绑定的完整标签包，其中必须包含逐条真实参考结果、独立模型裁判结果、盲化 A/B 可接受性评分和单独保存的 private key。合并器会拒绝缺失或重复行、标注后篡改候选报告、非法裁判结果、错误 private key，以及没有同时评价 A/B 的人评记录；只有合并后的报告才可能通过三个外部行为门禁。

因此以下项目仍然失败：41 条真实候选观测、与参考答案的非劣性、独立模型完整裁判、至少 95% 盲人可接受率，以及 AgentBench、τ²、Mem0、MEM1、BEAM 的官方可比成绩。

## 测试与复现

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.behavior_runtime_cli `
  --fixture tests/fixtures/behavior/agent_behavior_cases.v2.json `
  --repository-root . `
  --json-out .tmp/behavior-runtime-calibration.json
python -m klara.eval.public_memory_cli `
  --locomo-checkout .tmp/public-benchmarks/locomo `
  --json-out .tmp/locomo-public-memory.json
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

## 限制与下一步

本地确定性和公共来源契约已准备好，但它不是 Agent Product Freeze。只有在新增明确付费预算、完成真实候选和独立裁判、获得盲人标签并跑出官方可比 benchmark 后，才能重新生成总报告并考虑进入 KV Cache、轨迹数据和 HKU 训练。当前不声称达到普遍 ChatGPT 能力。
