# AgentLadder 训练过程（Qwen QLoRA + Klara SFT）

> 统一序列长度决策：**两个模型 `max_sequence_length` 都用 2048**。
> Qwen 2048 覆盖 91.6% 轨迹；Klara byte tokenizer 下 2048 覆盖 29.5%（byte 不压缩的硬约束，已记录在 `klara-bpe-tokenizer-plan.md`）。
> 所有数字来自 HKU 远程真实运行记录，不编造。

---

## 一、Qwen QLoRA Baseline

### 训练目标
用 `Qwen2.5-1.5B-Instruct` 做开源 Baseline，和自训练 Klara MoE 在同一套 Agent 轨迹、同一 Harness 下对比。

### 基座与量化
- 从官方 Instruct checkpoint 开始，不预训练。
- `bitsandbytes` 4-bit NF4 加载，冻结原始 Qwen 参数，计算精度 BF16。
- Attention 用 PyTorch SDPA。
- 只训练 LoRA Adapter，保存 Adapter，推理时重新加载 4-bit Base + Adapter。

### LoRA 配置
| 项 | 值 |
|---|---|
| rank r | 16 |
| alpha | 32 |
| dropout | **0.05**（不是 0.5） |
| target_modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| 可训练参数 | 18,464,768 |
| 总参数 | 1,562,179,072 |
| 可训练占比 | 1.182% |

### 数据
- `data/sft/train_2000.jsonl`，2000 条 Agent 轨迹。
- `seed=20260816` 打乱，5% 验证 → **1900 train / 100 val**。
- 类别：multi_tool 990、single_tool 984、sequential 26。
- 每条轨迹平均约 6.3 条 message（system/user/assistant/tool）。

### Loss
- **Assistant-only Cross Entropy Loss**：只对 assistant 的 content、tool_call、final answer 计算 loss，system / user / tool result 置 `-100`。
- 这是本次修正后的版本（原始实现误用了全序列 loss，已修复，见 `qwen-qlora-training-notes.md`）。

### 训练超参
| 项 | 值 |
|---|---|
| epochs | 3 |
| per_device_train_batch_size | 1 |
| gradient_accumulation_steps | 8（有效 batch 8） |
| 总步数 | **714**（= ceil(1900*3/8)，不是 1400 多） |
| learning_rate | 2e-4 |
| warmup_ratio | 0.03 |
| weight_decay | 0.0 |
| max_grad_norm | 1.0 |
| 精度 | bf16 |
| gradient_checkpointing | true |
| max_sequence_length | **2048** |

### 训练过程（真实 loss 曲线）
| epoch | loss | grad_norm |
|---:|---:|---:|
| 0.042 | 1.518 | 1.037 |
| 0.126 | 0.221 | 0.2574 |
| 0.463 | 0.066 | 0.1301 |
| 1.472 | 0.053 | 0.1301 |
| 2.059 | 0.040 | 0.1675 |
| 2.985 | 0.035 | 0.0860 |

最终平均 `train_loss = 0.0847`。

### 耗时与显存
- **训练耗时约 28 分钟**（`train_runtime = 1658s`，不是 1 小时）。
- 吞吐：3.438 samples/s，0.431 steps/s（约 2.3 s/step）。
- GPU：RTX 4080 SUPER，16GB。
- 峰值显存无持续采样记录，按 4bit + r16 LoRA + batch1/gradacc8 + gradient checkpointing 估算约 3~4GB。

### 产出
- 只保存 LoRA Adapter（`adapter_model.safetensors` 约 70.5MB）。
- 接入与 Klara 相同的 Agent Harness，在同一 dev/hidden 任务和冻结工具环境下比较 Task Success / Tool Call Accuracy / Invalid Call Rate。

---

## 二、Klara SFT

### 1. 数据
- 来自轨迹蒸馏的 SFT 轨迹：`data/sft/train_2000.jsonl`，2000 条，含正常对话回答。
- 划分：`val_ratio=0.01` → 约 **1980 train / 20 val**。
- 额外有冻结的 dev 200 / hidden 800 作为 Agent 评测集，不参与训练。

### 2. Tokenizer
- 与预训练相同：当前为 byte tokenizer（vocab 260）。
- 把 ChatML 渲染文本转成 token id。
- 已知问题：byte 不压缩，`max_sequence_length` 由 1024 改为 **2048**（覆盖 29.5%）；长期应换 BPE，见 `klara-bpe-tokenizer-plan.md`。

### 3. Loss Mask
- 与预训练的区别：不计算所有 token 的 loss。
- system / user 只作上下文，label 置 `-100`。
- 只对 **assistant 生成内容**（tool_call + final answer）计算 CE loss。

### 4. Forward 与 Loss
- 与预训练相同的前向和 CE loss，另加 MoE 辅助 loss。

### 5. 训练超参（真实）
| 项 | 值 |
|---|---|
| 参数量 | 107,322,360（107.3M，4-Expert Top-2 MoE） |
| max_sequence_length | **2048**（原 1024） |
| steps | 2000 |
| batch_size | 4 |
| gradient_accumulation_steps | 8（有效 batch 32） |
| learning_rate | 2e-5 |
| warmup_steps | 100 |
| weight_decay | 0.01 |
| grad_clip | 1.0 |
| precision | bf16 |
| seed | 20260816 |
| val_ratio / val_every | 0.01 / 50 |

### 6. 训练过程（真实 loss 曲线）
| step | train_loss | val_loss |
|---:|---:|---:|
| 10 | 2.505 | — |
| 100 | 0.156 | 0.179 |
| 200 | 0.091 | 0.091 |
| 1850 | 0.013 | 0.062 |
| 2000 | 0.0097 | 0.0622 |

- `initial_val_loss = 3.192`
- `final_val_loss = 0.0622`
- `loss_reduction_fraction = 98.05%`（验证 loss 从 3.19 降到 0.062）

### 7. 耗时与显存
- **训练耗时约 33 分钟**（2000 steps，约 1 step/s；500 steps 约 8.3 分钟，由 checkpoint mtime 推算）。
- GPU：RTX 4080 SUPER，16GB，torch 2.5.1+cu124，python 3.11.15。
- 峰值显存无持续采样记录，按 107M bf16 + batch4/seq1024 估算约 2~3GB。

### 8. Agent 回放与 Bad Case
SFT 中保留验证集，并把模型放回 Agent 里跑真实任务，除 validation loss 外还要看真实成功/失败。
对失败 case 按类别补数据回训练集。

实际发现的错误类别：
1. 工具调用错误
2. 参数错误
3. 工具幻觉
4. 提前生成答案
5. 重复调用
6. 模型放弃
