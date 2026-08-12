# AgentLadder 算法实验套件

语言：中文 | [English](./algorithm-suite.en.md)

路线图：[Klara Roadmap](../skills/roadmap.md)

最终机器报告：[Algorithm Suite Freeze](../reports/algorithm/algorithm-suite-freeze.md)

## 问题与可证伪假设

这组实验回答一个问题：从 Chapter 3 的 public trace 出发，能否在不修改
`KlaraLoop`、不依赖前端、也不收集隐藏思维链的前提下，建立一条可复现的
证据控制、评估、tiny Transformer、轨迹蒸馏、稀疏 MoE 和低精度链路？

假设只有在以下条件同时满足时成立：

- 证据与轨迹数据通过 schema、ID 链接、泄漏和确定性检查；
- required claim 没有 admissible support 时必须拒答；
- 自研 tiny decoder 能在固定 micro-corpus 上显著降低 loss 并精确重载；
- Qwen/DeepSeek 的 public hard labels 能提高 held-out tool decision accuracy；
- 四专家 top-2 token routing 不坍缩，且与 dense 使用相同数据和预算；
- FP16 和 FP4 的数值、存储和计算语义分别报告，不把 W4A16 说成 native FP4；
- 五个阶段能在同一个 HKU Slurm Job 中从文档命令完整重跑。

## 章节落位

| 路线内容 | Canonical home | 实现 |
| --- | --- | --- |
| public trace 与安全导出 | Chapter 3、Chapter 18、Lab A | `src/klara/eval` |
| claim-level evidence control | Chapters 12–13、Lab A | `src/klara/services/evidence` |
| tiny decoder pretrain | Lab B | `src/klara/training/model.py` 与 `trainer.py` |
| 多教师 public-trajectory distillation | Lab C | `src/klara/training/distillation.py` |
| 四专家 top-2 sparse MoE | Lab E | `src/klara/training/moe.py` |
| CUDA FP16 与 packed FP4/W4A16 | Lab H | `src/klara/training/quantization.py` |
| end-to-end regression bridge | Chapter 18 | `src/klara/eval/suite.py` |

训练包只读取已脱敏导出，不成为第二个 agent loop；`klara.core` 不导入 evidence、
eval 或 training 包。

## 一条命令的云端体验

先按本机 `C:\Users\jsj31\Desktop\HKU_GPU_FARM_HANDOFF.md` 建立 VPN/SSH
连接，然后在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/package_agentladder.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/submit_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/monitor_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/fetch_algorithm_suite_reports.ps1
```

`submit` 只在网关做环境准备，通过 `sbatch` 将正式计算送到 RTX 4080；`fetch`
只下载报告、日志和 checksums，所有 checkpoint 保留在 HKU 云端。

## Lab A：证据控制与轨迹评估

数据契约包含 run/turn/event/tool/source/claim ID、内容 hash、公开动作和 redaction
边界。`EvidenceController` 只允许有显式 supported link 和 citation 的 required claim
完成；contradicted 或 insufficient 会产生 abstention。

Job `133919` 的固定 gold fixture 结果：schema validation `1.0`、ID linkage
`1.0`、secret/hidden-reasoning finding `0`、citation precision/recall `1.0/1.0`、
abstention accuracy `1.0`。这些是 deterministic fixture 分数，不是开放域总体准确率。

## Lab B：仓库原生 tiny Transformer

模型为 UTF-8 byte tokenizer 上的 4 层 decoder：hidden size 128、4 个 attention
heads、2 个 KV heads、RMSNorm、RoPE、GQA、SwiGLU，共 `821,120` 参数。
它不是对预训练大模型的包装。

同一最终 Job 中，120 steps 的 FP32 CUDA 训练将 loss 从 `5.601286` 降至
`0.163015`，降幅 `97.09%`；checkpoint reload logits 的最大差为 `0.0`。

## Lab C：Qwen + DeepSeek public trajectory distillation

冻结 manifest 含 Qwen 和 DeepSeek 各 14 条、合计 28 条 public-contract examples，
train/validation/test 分别为 16/4/8，split hash 不相交。API teacher 路径只使用
hard-label SFT，KL weight 为 0；没有 raw prompt、raw tool result 或 provider hidden
reasoning。

在同一 Job 动态加载刚生成的 Lab B checkpoint 后，held-out tool decision accuracy
从 `0.125` 提升到 `1.0`，validation accuracy 为 `1.0`。这证明离线 contract fixture
的链路，不是在线 Qwen/DeepSeek 质量或成本 benchmark。

## Lab E：四专家 top-2 sparse MoE

每个 token 由 router 选择两个不同 expert，并将 selected weights 归一化；训练目标
同时包含 language-model loss、load-balance auxiliary loss 和 router z-loss。

在相同 micro-corpus、seed、120 steps、batch、optimizer、precision 和 scorer 下：

| 指标 | Dense | MoE |
| --- | ---: | ---: |
| 参数量 | 821,120 | 2,592,640 |
| loss 降幅 | 84.90% | 98.03% |
| peak allocated bytes | 61,149,696 | 115,504,640 |

MoE training-corpus expert loads 为 `[1721, 1626, 1719, 1758]`，max/min ratio
`1.081`；balanced fixture 为 `[16, 16, 16, 16]`，ratio `1.0`，未检测到 routing
collapse。该实验没有实现 distributed expert parallelism 或 fused production kernel。

## Lab H：CUDA FP16 与 E2M1 FP4/W4A16

FP16 路径使用 CUDA autocast 与 GradScaler 做真实 forward/backward；与 FP32 logits
的最大绝对差为 `0.001296669`，低于声明阈值 `0.02`。

FP4 路径覆盖所有 16 个 E2M1 code、奇偶长度 nibble pack/unpack、每 64 个权重的
FP16 block scale 和版本化 metadata。12 个 SwiGLU gate/up/down 投影的 FP16 baseline
为 1,179,648 bytes，packed codes + scales 为 313,344 bytes，节省 `73.4375%`。

held-out FP32 和 W4A16 accuracy 都为 `1.0`，所以 quality-failure 条件未触发，QAT
按契约没有运行。W4A16 forward 会把 packed weight 反量化到 activation dtype 再做
dense GEMM；这是 FP4 storage + dequantized compute，不是 native FP4 tensor-core 计算。

## 最终复现与产物

最终 HKU Job `133919` 在 `gpu-4080-409` 上用同一 source bundle
`3789e4d5395f44ac121045f73214ac9909096963a4e0b2981f166d112956d106`
顺序重跑五阶段，Slurm 状态 `COMPLETED`、exit code `0:0`、运行 37 秒。云端 Python
suite 为 229/229 passed。

最终报告不制造跨任务“总质量分”。每个数字保留自己的 fixture、scorer、manifest
和 checkpoint SHA。报告和 checkpoint 位于：

```text
/userhome/cs2/u3665453/AgentLadder/artifacts/algorithm-suite-freeze/job-133919/
```

本仓库只提交报告：

```text
docs/reports/algorithm/algorithm-suite-freeze.json
docs/reports/algorithm/algorithm-suite-freeze.md
```

## 限制与下一步

- gold/eval 数据和 micro-corpus 很小，只证明机制、谱系和可复现性；
- distillation 是 offline public-contract fixture，不代表在线 teacher 排名；
- MoE 比较固定数据和训练预算，但没有 active-FLOP matched kernel benchmark；
- FP4 仅量化 gated projections，计算路径不是 native FP4；
- QAT 代码与触发门已实现，但本次 W4A16 未退化，因此没有触发训练；
- 没有新增前端依赖，也没有完成生产 auth、分布式训练或大规模语料评估。
