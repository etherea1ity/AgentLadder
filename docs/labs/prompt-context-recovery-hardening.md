# Prompt、上下文、Memory 与恢复加固实验

语言：中文 | [English](./prompt-context-recovery-hardening.en.md)

## 目标

本实验修复第一轮全架构审计后发现的缺口，不进行模型训练。目标是得到一个可安全重启的 Agent：prompt 只描述实际可见能力，中文上下文预算保持保守，Memory 能抵抗提示注入并重建时间线，真实行为则与冻结的 GPT/Codex 参考答案比较。

## 架构改动

1. `klara.loop-checkpoint.v2` 保存可选的 controller 私有状态。上下文摘要会在下一次模型调用前恢复；checkpoint 对恢复 controller 后的有效 prompt 做哈希。API 的持久任务恢复也会先比较冻结的 run-profile 哈希。
2. 运行时指令按 capability 裁剪。只有 Memory 能力的 Agent 不再被要求调用不存在的 web、time 或 todo 工具。
3. token 估算改为 `ASCII/chars_per_token + 非 ASCII 码点`。摘要收缩使用同一个估算器，同时保留头尾、来源哈希和明确的用户更正锚点。
4. Provider 恢复加入有界 jitter，遵守数字型 `Retry-After`，并在 reasoning-only 或空生成后追加公开输出恢复指令。
5. Memory formation 接收不可信 JSON，不再把对话插值到 XML。检索先按相关性选择 top-k，再按时间线呈现，同时保留 `retrieval_rank`。
6. Memory 搜索保留完整问题。检索后只返回用户直接要求的最短事实，不自行追加候选项、括号日期或邻近事实。

## 验证

```powershell
python -m pytest -q

Push-Location apps/web
npm test
npm run build
Pop-Location
```

最终 LoCoMo 新鲜切分从哈希排序 offset 10 开始，共 100 题。两条路径都使用 DeepSeek V4 Flash、top-k 20、temperature 0 和 512 token 上限。直接 hybrid baseline 的 F1 为 0.455354、Recall@20 为 0.767917；真实 `KlaraHarness/KlaraLoop` Agent 的 F1 为 0.437246、Recall@20 为 0.782417，Memory 工具调用率、单次调用率和参数有效率均为 100%，P0 为 0。

41 个 observation 的真实行为回放在修复残缺 final answer 与空 provider 生成后，critical rate、normal task success 和重复稳定性均为 1.0，P0 为 0。

## 边界

本地代码/API 门禁已绿，但 Agent Product Freeze 仍未通过。Qwen 在冻结的独立 provider smoke 中返回 HTTP 401，且盲测人工标注尚不存在；这两个字段保持 unscored。本报告不允许连接 HKU、上传、提交 Slurm 或开始训练。
