# Klara byte tokenizer 截断诊断与 BPE 改造方案

> 状态：诊断完成，BPE 方案已推演；未开始重训。
> 结论：Klara 必须从 byte tokenizer 换到 BPE，否则长轨迹无法训练。

## 1. 现状

- tokenizer：`ByteTokenizer`（`src/klara/training/tokenizer.py`）
  - `vocab_size = 260` = 4 个 special（pad/bos/eos/unk）+ 256 个字节。
  - 一个 token = 一个 UTF-8 字节，**完全不压缩**。
- `config/experiments/klara_sft.toml`：
  - `[model] max_sequence_length = 1024`
  - `[tokenizer] type = "byte"`，但 `target_vocab_size = 28000`（说明原本就规划用 BPE，实际跑成了 byte）。
- 当前预训练 Job `134155` 与 SFT 用 byte tokenizer，checkpoint 依赖 byte 的 vocab=260。

## 2. 截断实测（byte tokenizer，train_2000.jsonl）

| 指标 | Klara token（byte） |
|---|---:|
| min / max | 1261 / 17105 |
| median | 2747.5 |
| p75 / p90 / p95 / p99 | 3942 / 5383 / 6050 / 11422 |
| <=1024 | **0%** |
| <=2048 | 29.5% |
| <=4096 | 77.75% |
| <=6144 | 95.2% |

结论：`max_sequence_length=1024` 下 **没有一条轨迹完整**，final answer 全部被截断。

## 3. 根因

1. byte tokenizer 不压缩：中文 1 字 = 3 字节 = 3 token；英文 1 字母 = 1 token。
2. 与 Qwen BPE 对比（同一条轨迹 `bfcl_single_tool_0000`）：
   - Qwen：4855 字符 -> 1400 token（约 3.47 字符/token）
   - Klara：3187 字符 -> 3189 token（约 1 字节/token）
   - 比值 Klara/Qwen = **2.28 倍**；中文轨迹可达约 3 倍。
3. Klara attention 是手写 `torch.matmul` 显式构造 `[batch, heads, seq, seq]`，显存/计算为 O(seq^2)。seq 无法像 Qwen 那样简单调大。

## 4. 显存 / 时间推算（当前 byte tokenizer + 手写 attention）

| 配置 | 覆盖 | 显存/时间风险 |
|---|---|---|
| seq 1024, batch 4 | 0% | 原来配置，可跑 |
| seq 2048, batch 4 | 29.5% | attention 矩阵 4 倍，约 9~10GB，16GB 卡勉强，约 4h |
| seq 4096, batch 1 | 77.75% | attention 矩阵 16 倍，约 10GB 但速度慢约 16 倍，约 16h |
| seq 6144 | 95.2% | 大概率 OOM（seq^2 显存） |

## 5. BPE 方案（推荐）

### 5.1 训练 BPE tokenizer
- 用 HF `tokenizers` 在预训练语料（FineWeb-Edu + 中文）上训练 BPE。
- `target_vocab_size = 28000`（config 已预留）。
- 特殊 token：pad/bos/eos/unk 对齐现有 `ByteTokenizer` 约定。
- 输出 `tokenizer.json`，替换 `artifacts/klara-moe-pretrain/tokenizer`。

### 5.2 改模型 config
- `vocab_size: 260 -> 28000`。
- embedding 与 lm_head 尺寸随之变化：
  - hidden_size=600，tie_word_embeddings=true。
  - embedding 增加约 `(28000-260)*600 ≈ 16.6M` 参数（tie 情况下只加一份）。
  - 107.3M -> 约 123.9M 参数（以实际统计为准）。

### 5.3 重新预训练（必须）
- embedding 层变化导致 `134155` 的 checkpoint **无法复用**，需要重跑预训练。
- 这是最大成本项。

### 5.4 重新 SFT
- BPE 后 token 长度接近 Qwen（压缩约 2~3 倍），`max_sequence_length` 可保持 2048 或降到 1024。
- 重新用 `train_2000.jsonl` 做 assistant-only SFT。

## 6. 替代方案（不换 BPE，工程改造 attention）

- 保持 byte tokenizer，但给 attention 上 Flash Attention / SDPA + gradient checkpointing，支撑 seq 4096~6144。
- 优点：不用重训预训练。
- 缺点：byte tokenizer 仍然低效，长序列显存/速度依然紧张，且简历里 tokenizer 设计不够干净。

## 7. 决策点

| 方案 | 成本 | 结果 |
|---|---|---|
| A. 换 BPE 重训预训练 | 高（重跑 2.5B 语料预训练） | 干净、可扩展，与 Qwen 口径对齐 |
| B. 保持 byte + Flash Attention | 中（改 attention 代码） | 不用重训，但 tokenizer 仍低效 |

建议：若时间允许走 A；简历要写“BPE tokenizer + 124M MoE”则 A 是唯一自洽路径。
