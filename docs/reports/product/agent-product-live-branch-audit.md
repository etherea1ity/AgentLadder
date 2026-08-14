# Agent 产品分支真实回测审计

语言：中文 | [English](./agent-product-live-branch-audit.en.md)

状态：**审计通过；历史失败保留**

- 冻结产品分支：`16`
- 历史精确提交真实通过：`1`
- 历史精确提交真实失败：`1`
- 历史提交无兼容真实 runner：`14`
- 最新累计运行时覆盖：`16/16`

## 结论

最新累计运行时覆盖全部 16 个冻结产品能力，相关确定性门、真实 API 行为回测与真实服务检查通过。历史提交证据是另一个维度，不能与最新累计结果混写。

## 历史精确提交

| 分支 | 提交 | 结果 |
| --- | --- | --- |
| `codex/agent-runtime-integration` | `ac6f83e` | detached worktree 中真实 DeepSeek `3/3`，14/14 检查，0 P0，0 未授权写入 |
| `codex/agent-product-benchmarks` | `1642ae6` | 真实回放约 212 秒后因 `all_model_candidates_failed` 中止；旧 runner 无 checkpoint，失败不重标为通过 |
| 其余 14 个产品分支 | 各冻结提交 | 历史代码早于兼容真实 runner；标记为 `not_executable_with_current_runner`，由最新累计运行时覆盖 |

## 证据边界

逐分支提交、状态和证据文件见同目录 JSON。`passed: true` 表示审计完整且没有虚报；它不表示两个可执行历史提交都通过，也不解除独立裁判、人工盲审和正式公开竞品评测的冻结阻塞。
