# Agent Development And Algorithm Resume Bullets

Use only with the scope qualifiers below.

## Chinese

- 从零搭建可观测 Agent runtime：以统一 public event stream 驱动 hooks、JSONL
  trace、工具生命周期与调试投影，并在 core 外实现 claim-level 证据控制、矛盾检测、
  引用校验和证据不足拒答；固定回归集实现 schema/ID linkage 100%、零敏感信息与隐藏
  reasoning 泄漏、citation precision/recall 和 abstention accuracy 均为 100%。
- 自研 82.1 万参数 decoder-only Transformer（RMSNorm、RoPE、GQA、SwiGLU）及训练、
  checkpoint/reload 链路；在 HKU RTX 4080 上将 micro-corpus loss 降低 97.09%，并用
  Qwen/DeepSeek public hard-label 轨迹将 held-out tool-decision accuracy 从 12.5% 提升到 100%。
- 实现 4-expert token-level top-2 sparse MoE、load-balance/z-loss 与 routing 诊断；同预算
  实验 loss 降低 98.03%，expert load ratio 1.081；实现 CUDA FP16 AMP 和 E2M1 FP4
  packed W4A16，将 12 个 gated projections 的含 scale 存储降低 73.44%，held-out accuracy 无下降。
- 建立 HKU Slurm 云端可复现流水线：source bundle、config/data/scorer/checkpoint SHA-256、
  单 Job B→C→H checkpoint lineage、远端 checksums 与残留进程检查；最终 229/229 测试通过。

## English

- Built an observable agent runtime around one public event stream for hooks,
  JSONL traces, and tool lifecycle events; added claim-level evidence control,
  contradiction/citation checks, and abstention outside the core loop, reaching
  100% schema/linkage and deterministic fixture metrics with zero secret or
  hidden-reasoning leakage findings.
- Implemented an 821K-parameter decoder-only Transformer from scratch
  (RMSNorm, RoPE, GQA, SwiGLU), reducing bounded micro-corpus loss by 97.09% on
  an HKU RTX 4080; distilled public Qwen/DeepSeek hard labels to improve held-out
  tool-decision accuracy from 12.5% to 100% on the frozen contract fixture.
- Implemented a four-expert token-level top-2 sparse MoE with load-balance and
  router z-loss diagnostics (98.03% loss reduction, 1.081 expert-load ratio),
  plus CUDA FP16 AMP and E2M1 packed W4A16 that cut gated-weight code-plus-scale
  storage by 73.44% with no held-out accuracy loss.
- Built a cloud-only Slurm reproducibility pipeline with source, config, data,
  scorer, and checkpoint hashes; enforced same-job B-to-C-to-H checkpoint
  lineage, remote checksum verification, and a 229/229-test final gate.

## Scope Qualifiers

The 100% scores are frozen small-fixture results. Distillation is offline public
contract supervision, MoE is a tiny controlled experiment, and FP4 is packed
storage with dequantized W4A16 compute rather than native FP4 hardware execution.
