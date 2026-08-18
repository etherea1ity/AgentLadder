# Klara 最小实验闭环报告

- 生成时间: 2026-08-17
- 目标: 完成 Base → SFT → QLoRA/基线 → 统一评测的最小闭环，不跑 GRPO。

## 模型与数据

- Klara: 4-expert top-2 Sparse MoE，RMSNorm / RoPE / GQA / SwiGLU
- 参数量: total 107,322,360（约 107.3M），expert 100,224,000，shared 7,098,360，per-token active 约 57.2M
- tokenizer: byte（vocab 260），max_seq 1024
- 预训练 Base: checkpoint_0002000（约 131M byte-tokens；完整 30k-step 预训练仍在后台继续）
- Klara SFT: 2000 steps，2000 条 clean Teacher 轨迹，final_val_loss 0.0622
- Qwen: Qwen2.5-1.5B-Instruct，QLoRA（nf4，LoRA r=16）+ no_finetune 基线
- 数据: train 2000 / dev 200 / hidden 800，task-level disjoint

## Dev 200 结果

| 模型 | task_success | tool_call_accuracy | invalid_call_rate | mean latency |
|---|---:|---:|---:|---:|
| DeepSeek V4 Pro | 0.1700 | 0.3333 | 0.5810 | 28.8s |
| Qwen no_finetune | 0.1200 | 0.2504 | 0.6925 | 2.35s |
| Qwen QLoRA | 0.1350 | 0.2879 | 0.5810 | 6.37s |
| Klara SFT | 0.0150 | 0.0150 | 0.0 | 10.3s |

## Hidden 800 结果

| 模型 | task_success | tool_call_accuracy | invalid_call_rate | mean latency |
|---|---:|---:|---:|---:|
| DeepSeek V4 Pro | 0.1237 | 0.2671 | 0.6141 | 20.7s |
| Qwen no_finetune | 0.1125 | 0.2313 | 0.6864 | 2.57s |
| Qwen QLoRA | 0.1238 | 0.2552 | 0.6291 | 6.19s |
| Klara SFT | 0.0213 | 0.0213 | 0.0 | 10.8s |

## 推理实测（Klara MoE，RTX 4080 SUPER，batch=1，checkpoint_0002000）

- tokens_per_second: 74.37
- P95 prefill TTFT: 17.42 ms
- peak VRAM: 440.4 MB
- W4A16: FP4 packed 存储 53.2MB vs FP16 200.4MB，节省 73.44%，压缩比 3.76x

## 结论与边界

- 整体 task_success 都偏低，原因是评测集是“必须精确调用指定工具”的严格合成任务。
- 排序合理: DeepSeek ≈ Qwen QLoRA > Qwen no_finetune > Klara SFT。
- Klara SFT 明显欠训练：Base 只训了约 131M byte-tokens，SFT 也只有 2000 steps，输出尚不能稳定生成工具调用。
- 本轮为最小闭环验证，不是性能最优结论；下一步应增加 Base 预训练 token 数并重做 SFT。
- 未跑 GRPO（按用户要求）。
