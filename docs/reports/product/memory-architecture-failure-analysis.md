# Memory 架构失败分析

语言：中文 | [English](./memory-architecture-failure-analysis.en.md)

100 题 repair replay 中，工具协议与检索已修复：100/100 正常结束，合法单次 `memory_search` 为 100%，Recall@20 从 0.6521 提升到 0.7402，且 P0 为 0。

最终门仍失败。Agent F1 为 0.3910，低于同模型专用 QA baseline 的 0.4619；Exact Match 为 0.11，对照为 0.25。剩余问题不是“没有取到证据”，而是通用 Agent system prompt、ranked observation 组织和回答抽取不如专用 QA prompt。

已修复的结构问题包括：跨 owner 的全局 Memory 主键覆盖、Memory 请求误入 Web Research、untrusted wrapper 导致证据计分为零、learned dense 覆盖 sparse 信号。Dense/Sparse 已改为 RRF。

这次复测使用同一 100 题，只能作为 repair replay，不能冒充新的隐藏集。Agent Product Freeze 与模型训练继续阻断。
