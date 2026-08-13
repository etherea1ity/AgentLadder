# Chapter 18：生产运行时与评测桥接——先冻结 Agent 行为契约

语言：中文 | [English](./ch18-production-runtime-and-eval-bridge.en.md)

上一章：[Chapter 17：MCP 与外部工具](../skills/roadmap.md#chapter-17---mcp-and-external-tools)

下一章：[Lab A：轨迹数据与评测](../skills/roadmap.md#lab-a---trace-dataset-and-evaluation)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 先冻结用例、权限、预算和评分规则，再执行候选并发布机器可读证据；任何关键安全失败都不能被平均分掩盖。

![Klara Agent 行为评测契约](../assets/ch18-agent-eval-contract.svg)

| 看到什么 | 门禁做什么 |
| --- | --- |
| 关键用例有一次失败 | 直接失败，不用平均分抵消 |
| 普通任务成功率低于 `0.95` | 阻止阶段晋级 |
| P0 大于 `0` | 阻止发布 |
| 契约控制探针通过 | 只证明评测管线可用，不证明 Agent 已完成 |

## 快速体验

从仓库根目录运行：

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.behavior_cli `
  --fixture tests/fixtures/behavior/agent_behavior_cases.json `
  --config config/evaluation/agent_behavior.toml `
  --repository-root . `
  --json-out docs/reports/product/agent-eval-contract.json `
  --markdown-out docs/reports/product/agent-eval-contract.md `
  --markdown-en-out docs/reports/product/agent-eval-contract.en.md
```

你应该看到 `passed: true` 和 `gate_kind: contract_control_probe`。再运行 `./scripts/dev.ps1`，打开侧栏的 **Evaluations**，页面只展示聚合结果与 split hash，不展示隐藏用例正文或盲评身份。

## 真实问题：为什么不能先写功能再随便测一下

如果评分规则跟着候选结果变化，失败就可以被重新解释；如果把所有分数平均，权限越界也可能被许多简单成功题掩盖；如果评测页面暴露隐藏题，后续实现会无意中针对题目优化。

本阶段因此先完成 Phase 0B 的评测合同。它不是 Chapter 18 的最终完成声明：真实轨迹导出、候选 Agent 接管、生产认证与远程训练仍属于后续阶段。

## 机制一：冻结输入而不是冻结结论

`agent_behavior_cases.json` 给每个行为用例保存来源、许可证、split、风险、工具、权限、期望状态、禁用动作、预算与参考公开答案。`KlaraBehaviorCase` 在载入时拒绝重复 ID、冲突动作和跨 split 的同一场景族。

<details>
<summary>查看真实 schema 与 split 隔离</summary>

```text
src/klara/eval/behavior.py
tests/fixtures/behavior/agent_behavior_cases.json
config/evaluation/agent_behavior.toml
```

`stable_hash` 使用稳定 Unicode JSON 序列化。报告保存整份 fixture 的 SHA-256，也为 development、validation、hidden regression 和 adversarial 分别保存 hash。

</details>

## 机制二：确定性安全和答案质量分开计算

`score_observation` 检查必须调用、禁止调用、状态、产物、不变量、禁用声明以及 step/token/cost/latency 预算。关键用例重复五次，普通用例重复三次。P0 必须为零，关键确定性成功率必须为 `1.0`。

<details>
<summary>查看评分与报告聚合</summary>

```text
src/klara/eval/behavior.py
src/klara/eval/behavior_report.py
tests/klara/eval/test_behavior_contract.py
```

独立 judge 与人工接受率是单独字段。`reference_gap` 衡量冻结候选相对参考的差距，但通过只对当前用例、工具、权限、预算和评分器有效。

</details>

## 机制三：控制探针只验证管线

当前 CLI 运行的是具名 `contract_control_probe`。它把每个冻结参考答案作为合规观察送进评分器，用来验证 schema、阈值、重复稳定性、文档检查与盲评队列连接是否正确。

```text
control probe PASS -> evaluation substrate is wired correctly
candidate Agent PASS -> not measured in this phase
general GPT equivalence -> never implied
```

这条边界会同时写入 JSON、双语 Markdown 和前端状态卡，避免把“评测工具可用”误报成“产品能力通过”。

## 机制四：前端只读取安全投影

`/api/evaluations/summary` 从 JSON 报告投影状态、计数、指标、检查与 split hash。它不返回 `case_scores` 或 `human_review_queue`。前端有加载、无报告、失败和通过状态，并支持响应式与深色模式。

<details>
<summary>查看 API 和可视化入口</summary>

```text
src/klara/eval/catalog.py
apps/api/routes/evaluations.py
apps/web/src/components/EvaluationDashboard.tsx
apps/web/src/styles/app.css
```

评测页面是观察面，不是评测计算器；JSON 报告仍是唯一事实来源。

</details>

## 运行与验证

```powershell
python -m pytest -q
Push-Location apps/web
npm test
npm run build
Pop-Location
git diff --check
```

评测专项测试还覆盖 schema 拒绝、split 泄漏、关键失败不可平均、盲评随机槽位、文档中英文结构和 API 隐藏字段。

## 小实验

1. 在临时副本里把一个关键 control observation 的 `p0_failures` 加一项，确认总门禁失败。
2. 把同一个 `scenario_family` 放进两个 split，确认 fixture 无法载入。
3. 临时删除报告，确认 Evaluations 页面进入 `not_run`，而不是伪造零分。

## 本阶段边界与下一步

Phase 0B 交付的是可复用评测契约和聚合证据面。下一条产品分支回到 Chapter 4，完成 harness/config；此后每章都必须把真实 Agent 候选接进同一冻结契约，达到门槛后才能晋级。HKU、Slurm 与大模型训练在 local pre-HKU freeze 前保持禁用。
