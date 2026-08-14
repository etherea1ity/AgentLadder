# Prompt、上下文、Memory 与恢复加固

语言：中文 | [English](./prompt-context-recovery-hardening.en.md)

- 本地代码/API 门禁：`PASS`
- Agent Product Freeze：`FAIL`
- HKU 训练已开始：`false`

## 结果

- Python：收集 `510` 项，跳过 `2` 项。
- Web：`20` 个文件、`71` 项测试，生产构建通过。
- 逐章门禁：`12/12`。
- 行为回放：critical `1.0`，normal `1.0`，P0 `0`。
- LoCoMo F1：direct `0.455354`，Agent `0.437246`，差值 `-0.018108`。
- LoCoMo Recall@20：direct `0.767917`，Agent `0.782417`。

## 阻塞项

- Qwen 独立评审凭据在冻结的真实 smoke 中返回 HTTP 401。
- 尚未产生盲测人工标签，不能把模型评分冒充为人工评分。
