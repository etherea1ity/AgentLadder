# Agent 架构与 Memory Benchmark 总结

语言：中文 | [English](./memory-benchmark-summary.en.md)

当前结论：**架构冻结通过，但 Agent Product Freeze 未通过，不能开始 HKU 模型训练。**

## 架构和真实运行

- 审计了 `34` 个远程分支对应的 `32` 个唯一提交；`34/34` 可编译，`33/34` 通过各自历史测试。旧 `origin/rag` 独立遗留线仍有 `9` 个失败。
- 所有历史分支按当前完整架构契约均不完整；修复只集成到最新可靠分支，没有篡改历史教学快照。
- 最新分支通过 `12/12` 章级架构门禁、`498` 个 Python 测试（`2` 个环境跳过）、`71` 个前端测试和生产构建。
- DeepSeek 真实 runtime integration 为 `3/3` cases、`14/14` checks，未授权 mutation 为 `0`；evidence/MCP/team tooling 为 `3/3`，P0 为 `0`。
- 真实 Harness 行为回放为 `40/41`（`97.56%`），普通任务 `100%`、关键任务 `95%`、P0 为 `0`。但独立 judge、reference 和盲评尚未导入，因此不能宣称行为门禁通过。唯一 deterministic miss 是语义正确的中文拒绝被已冻结的词法 matcher 拒绝；观察结果后没有改隐藏 fixture。

## LoCoMo Memory 结果

100 题 repair replay 全部正常结束，单次合法 `memory_search` 为 `100%`，Recall@20 为 `0.7402`，略高于同模型 direct-hybrid baseline 的 `0.7340`。这证明 owner 隔离、Memory 路由、工具协议和 dense/sparse RRF 检索已经修到门槛以上。

但最终 F1 只有 `0.3910`，低于同模型专用 QA baseline 的 `0.4619`，差值 `-0.0709`，超过允许的 `-0.03`；Exact Match 为 `0.11`，baseline 为 `0.25`。剩余瓶颈已经定位到通用 Agent 的答案合成，而不是取证失败。

这 100 题是修复后的同集 replay，只能验证修复，不能冒充新的隐藏集。下一次必须使用新鲜隐藏切分。

## Mem0

没有伪造 Mem0 分数。官方 `memory-benchmarks` 固定提交的 Dockerfile 引用了已删除的 `feat/v3-pipeline` 分支，因此官方运行时当前不可复现。SDK compatibility adapter 也没有被冒充成 byte-identical 官方结果。

## 当前门禁

- Agent Architecture Freeze：`PASS`
- Agent Product Freeze：`FAIL`
- HKU 模型训练：`BLOCKED`

下一步必须先修复 Memory 答案合成，在新隐藏集复测，补齐独立 judge/reference/盲评，并以可追溯的官方运行时复现 Mem0；全部通过后才允许训练。
