# Qwen QLoRA 训练复盘与修正笔记

> 状态：已修正 loss mask 与序列长度，重训 Job `134195` 已提交（排队中）。
> 数据来源：HKU 远程 `/userhome/cs2/u3665453/AgentLadder` 下 `runs/`、`logs/`、`artifacts/` 的真实运行记录。

## 1. 原始训练（Job 134161）真实参数

| 项 | 值 |
|---|---|
| 基座模型 | `Qwen/Qwen2.5-1.5B-Instruct` |
| 总参数量 | 1,562,179,072 |
| 量化 | bitsandbytes 4-bit NF4，compute dtype bf16 |
| Attention | sdpa |
| LoRA rank / alpha / dropout | 16 / 32 / 0.05 |
| target_modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| 可训练参数 | 18,464,768（1.182%） |
| 数据 | `data/sft/train_2000.jsonl`，2000 条 |
| train / val 划分 | 1900 / 100（seed 20260816，5% val） |
| max_sequence_length | 1024 |
| epochs / batch / grad_accum | 3 / 1 / 8（有效 batch 8） |
| 总步数 | 714（= ceil(1900*3/8)） |
| lr / warmup / wd / clip | 2e-4 / 0.03 / 0 / 1.0 |
| 精度 / grad checkpointing | bf16 / true |
| 节点 / GPU | gpu-4080-410 / RTX 4080 SUPER 16GB |

## 2. 原始训练的 loss 曲线（真实摘录）

| epoch | loss | grad_norm |
|---:|---:|---:|
| 0.042 | 1.518 | 1.037 |
| 0.126 | 0.221 | 0.2574 |
| 0.463 | 0.06603 | 0.1301 |
| 1.472 | 0.05333 | 0.1301 |
| 2.059 | 0.03997 | 0.1675 |
| 2.985 | 0.03501 | 0.08596 |

- 最终平均 `train_loss = 0.08469`。
- 注意：这个低 loss 被稀释过，见下方问题 1。

## 3. 原始训练的耗时与吞吐

- `train_runtime = 1658s ≈ 27.6 min`
- `train_samples_per_second = 3.438`
- `train_steps_per_second = 0.431`（平均约 2.3 s/step）

## 4. 显存

- GPU 总显存 16376 MiB（16GB）。
- 训练结束 `memory.used = 2 MiB`（模型已卸载），**日志无持续峰值采样**。
- 估算峰值约 3~4GB（4bit 权重 ~0.8GB + LoRA 优化器 ~0.2GB + 激活 ~1-2GB，gradient checkpointing 开启）。
- 若要写进简历，建议标“估算”，或重跑加 nvidia-smi 采样实测。

## 5. 经历（3 次 job）

| Job | 结果 |
|---|---|
| 134157 | 失败：`TrainingArguments.__init__() got an unexpected keyword argument 'warmup_ratio'` |
| 134159 | 失败：`Trainer.__init__() got an unexpected keyword argument 'tokenizer'` |
| 134161 | 成功，产出 adapter（~70.5MB） |

## 6. 发现的问题

### 问题 1：loss 不是 assistant-only（关键 bug）

原始 `tokenize_example`：

```python
return {"input_ids": input_ids, "labels": list(input_ids)}
```

配 `DataCollatorForLanguageModeling(mlm=False)`，只把 padding 置 -100，**system / user / tool 的 token 全部参与 CE loss**。

实测第一条轨迹：`non--100 labels = 1024 / 1024`，连 `<|im_start|>system` 都被当作 label。这与简历“Assistant-only CE Loss”不符。

### 问题 2：max_sequence_length=1024 截断严重

用 Qwen tokenizer 对 `train_2000.jsonl` 统计（完整 tokenize，不截断）：

| 指标 | Qwen token |
|---|---:|
| min / max | 545 / 6045 |
| median | 1102 |
| p90 / p95 / p99 | 2010 / 2310 / 4026 |
| <=1024 | 38.6% |
| <=2048 | 91.6% |
| <=3072 | 97.75% |

1024 下 1232/2000（61.6%）被截断，其中 338 条最后一个 final answer 缺 `<|im_end|>`。

## 7. 修正方案（已实施）

1. `src/klara/qwen/qlora_sft.py` 新增 `_assistant_only_labels()`：
   - 定位 `<|im_start|>assistant\n` 到 `<|im_end|>`；
   - 只保留 assistant 的 content / tool_call / final answer 参与 loss；
   - system、user、tool response 置 -100。
2. `config/experiments/qwen_qlora.toml`：`max_sequence_length = 1024 -> 2048`（覆盖 91.6%）。

## 8. 重训

- Job：`134195`（Qwen QLoRA SFT）
- 已同步远程 config 与代码，等 GPU 配额释放后自动运行。
- 产出目录：`artifacts/qwen-qlora-sft/job-134195`，不会覆盖旧的 `job-134161`。
