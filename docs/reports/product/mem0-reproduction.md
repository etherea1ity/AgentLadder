# Mem0 复现状态

语言：中文 | [English](./mem0-reproduction.en.md)

官方 `memory-benchmarks` 固定提交的 Mem0 Dockerfile 引用了已经删除的 `feat/v3-pipeline` 分支，因此官方容器无法按提交原样构建。本阶段不声称 Mem0 分数，也不把当前 SDK compatibility adapter 冒充为官方逐字节复现。

下一步必须固定修正后的官方镜像，或带完整来源地 vendoring 被删除实现，再使用完全相同的 LoCoMo 子集、回答模型、生成预算和 scorer。
