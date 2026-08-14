# Agent 产品真实回测计划

语言：中文 | [English](./agent-product-live-backtest-plan.en.md)

Status: **IN PROGRESS**

## 当前事实

此前 Chapter 4–18 的多数行为结果来自确定性测试或 `contract_control_probe`。真正使用外部模型的产品证据只有 DeepSeek V4 Flash 的 3 条 Runtime Integration smoke；KlaraBench v2 的 `41/41` 是脚本参考校准，不是模型成绩。

## 比较单位

每条样本比较完整的公开行为：问题与上下文 → 工具选择、参数和顺序 → 工具 observation → 持久状态变化 → 最终回答。GPT/Codex 只提供公开参考答案和公开动作路径，不收集隐藏推理；DeepSeek 与 Qwen 都必须经过真实 `KlaraHarness`。

## 执行顺序

1. 验证 DeepSeek、Qwen 的真实认证与模型 ID。
2. 把每个冻结阶段的能力扩展成跨章节行为矩阵。
3. 用 DeepSeek V4 Flash 与 Qwen 3.7 Flash 跑同一批样本。
4. 用 GPT/Codex 公开参考逐条计算非劣性。
5. DeepSeek 输出由 Qwen Max 裁判，Qwen 输出由 DeepSeek Pro 裁判。
6. 保存错工具、错参数、假成功、答非所问、越权、奇怪追问和无关计划，回到所属阶段修复并重跑。
7. 生成盲评队列；不得由生成者伪造人工标签。
8. 所有强制门禁通过后才允许 Agent Product Freeze。

## 预算与停止条件

本轮 API 总硬上限为 20 美元等值，同时设置 DeepSeek 10 美元、Qwen 75 元人民币和 900 请求的子上限。使用官方价格、cache-miss/list price 和 provider usage 保守计费；任一上限即将超过时停止。

模型训练、HKU、KV Cache 和大规模轨迹收集仍由 Agent Product Freeze 阻挡。
