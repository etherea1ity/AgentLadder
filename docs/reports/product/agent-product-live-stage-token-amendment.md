# Agent 产品实时阶段 Token 合同修订

语言：中文 | [English](./agent-product-live-stage-token-amendment.en.md)

- 用例：`dev-todo-multistep-en-001`
- 字段：`limits.maximum_tokens`
- 原值：`120`
- 新值：`180`
- 状态：`requires_fresh_live_rerun`

原因：该用例要求一次包含三个步骤的公开原生工具调用和最终状态回答。原 120-token 上限低于同一 KlaraBench v2 中其他同类工具用例采用的 180 或 220 token，并在回答质量判断前错误拒绝了语义正确的工具参数。

防作弊边界：Provider 生成上限仍为 800，最大步骤仍为 2；必需工具、状态、不变量和参考答案均未改变。修订前报告保留，修订后必须重新执行真实 API 回测，不能离线改分。
