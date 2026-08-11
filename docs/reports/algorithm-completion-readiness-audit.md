# AgentLadder Algorithm Completion Readiness Audit

Date: 2026-08-11

Status: planning gate passed

## Decision

The algorithm work will continue from `origin/chapter-3-hooks-and-trace` commit
`c12530f`. Existing course branches remain historical teaching checkpoints. The
old RAG branches will not be merged into the current `src/klara` architecture;
their useful contracts and tests will be ported deliberately.

The work is unattended after planning. A stage may advance only when every
required command and metric gate for that stage passes. A failing gate triggers
repair and rerun, not a scope reduction and not a request for an intermediate
user review.

## Current Evidence

- Remote refs were refreshed with `git fetch --all --prune`.
- Current baseline commit: `c12530f`.
- Baseline Python suite: 168 tests collected and passed.
- Repository-level `AGENTS.md`: none.
- Configured live teachers: Qwen/DashScope and DeepSeek credentials are present;
  secret values were not read or printed.
- Python: 3.11.5.
- PyTorch: 2.5.1+cu121.
- CUDA is available on an NVIDIA GeForce RTX 3050 Laptop GPU.
- GPU compute capability: 8.6; VRAM: 4 GB; BF16 support is reported by PyTorch.
- System RAM: 16 GB. The audit observed low free-memory periods, so all default
  loaders must use conservative worker counts and bounded in-memory datasets.
- Native FP4 arithmetic is not available on this GPU. The mandatory FP4 result
  is therefore a truthful E2M1 block-scaled W4A16 reference path with packed
  storage; native FP4 remains an optional hardware-specific backend.

## Branch Audit

| Branch | Role | Decision |
| --- | --- | --- |
| `origin/chapter-1-minimal-loop` | Minimal loop teaching checkpoint | Preserve; no new algorithm work |
| `origin/chapter-2-tool-calling` | Tool registry/executor/evidence-discipline checkpoint | Preserve; reuse tool contracts and tests |
| `origin/chapter-3-hooks-and-trace` | Current linear course head | Authoritative implementation baseline |
| `origin/main` | Synchronized Chapter 2 checkpoint | Do not use as the algorithm base |
| `v0.3-agentic-rag` | Older RAG architecture and frontend-neutral work | Read-only source of RAG contracts and lessons |
| `origin/rag` | Divergent full Agentic RAG/paper-corpus implementation | Port selected ideas; never merge its package tree wholesale |
| `codex/ch03-algorithm-roadmap` | Current planning integration branch | Finish roadmap, Skill, readiness report, and planning gate |

The old RAG branches use `src/agent_ladder`; the current course uses
`src/klara`. They also encode a different chapter order. A tree merge would
reintroduce duplicate runtimes, rule-based routing, frontend scope, and stale
chapter semantics.

### Assets to port from old RAG work

- `SourceCard`, `Citation`, and `AnswerFrame` boundaries.
- `EvidencePack` as the only writer-visible evidence input.
- `DecisionRecord` and workflow trace concepts.
- Explicit insufficient-evidence output.
- Retrieval/evidence/citation tests and the writer-cannot-see-raw-chunks test.

### Assets to reject or rewrite

- `src/agent_ladder` package layout.
- Chapter-specific orchestration inside the core runtime.
- Keyword/domain truth patches and rule intent routers.
- Token-overlap claim verification presented as semantic support.
- Tests that accept `passed`, `failed`, or `revised` as equally successful.
- Frontend completion as an algorithm gate.

## Current Chapter 3 Boundary

The latest branch already contains `WebResearchController`, `EvidenceLedger`,
search/fetch state, readiness policy, compacted observations, trace events, and
tests. This is source-level readiness control: it answers whether enough fetched
sources exist and whether the runtime may finalize.

It is not claim-level evidence control. The new work must add, outside
`src/klara/core`:

- stable claims;
- evidence records with provenance and hashes;
- claim-to-evidence links;
- `supported`, `contradicted`, and `insufficient` judgments;
- explicit abstention;
- deterministic scoring and regression reports.

This distinction prevents duplicate WebResearch state machines and preserves
the Chapter 3 hook/trace teaching claim.

## MiniMind Reference Audit

Local reference: `C:\Users\jsj31\Desktop\minimind`, commit `393e387`.

| MiniMind idea | AgentLadder use |
| --- | --- |
| Small decoder-only Transformer | Reimplement a smaller repository-native teaching model |
| RMSNorm, RoPE, grouped KV attention, SwiGLU-style FFN | Reuse the architectural ideas with shape and causality tests |
| Dense/MoE switch | Preserve through one shared block/config interface |
| Four expert configuration | Use four experts, but require top-2 routing rather than MiniMind's default top-1 |
| Router auxiliary loss | Add load-balance loss, router z-loss, utilization and entropy metrics |
| Pretrain/SFT loops | Rebuild as importable library code plus thin CLI, manifests, and deterministic tests |
| CE plus temperature-scaled KL | Use for a local-logit teacher only |
| Tool-use conversation dataset | Convert Klara public trajectories, with strict redaction and split lineage |
| Tool-call evaluation | Replace demo printing with machine-readable exactness and evidence metrics |

MiniMind code is a design reference, not a file-copy source. The new code must
fit current AgentLadder conventions and tests.

### MiniMind patterns explicitly excluded

- `signal.SIGALRM`, which is not a portable Windows timeout mechanism.
- Rewarding hidden `<think>` length or collecting provider-hidden reasoning.
- `eval`-based tool execution.
- Random test seeds in an evaluation command.
- Saving half-precision weights without a manifest and verification hash.
- Treating vocabulary truncation as valid logit distillation across unrelated
  teacher tokenizers.

## Target Package Layout

```text
src/klara/services/evidence/
  contracts.py
  controller.py
  verifier.py

src/klara/eval/
  trajectory.py
  dataset.py
  scorers.py
  report.py
  cli.py

src/klara/training/
  config.py
  tokenizer.py
  data.py
  model.py
  moe.py
  precision.py
  checkpoint.py
  trainer.py
  distillation.py
  cli.py

tests/fixtures/algorithm/
config/experiments/
docs/reports/algorithm/
```

`src/klara/core` may expose generic events and controller protocols, but it must
not import evidence, eval, or training packages. Training consumes redacted
exports; it does not become a second agent loop.

## Stacked Implementation Branches

Each branch starts only after the previous branch is committed and its gate is
green. Branches are stacked to preserve an auditable progression.

| Order | Branch | Required content |
| --- | --- | --- |
| 0 | `codex/ch03-algorithm-roadmap` | Roadmap, readiness audit, strict-completion Skill |
| 1 | `codex/lab-a-evidence-eval` | Trajectory schema/export, claim evidence control, gold fixtures, scorers, reports |
| 2 | `codex/lab-b-tiny-pretrain` | Byte tokenizer, tiny dense decoder, trainer, checkpoints, deterministic pretrain report |
| 3 | `codex/lab-c-trajectory-distillation` | Qwen/DeepSeek teacher collection, filters, hard-label SFT, local-logit KL option, held-out report |
| 4 | `codex/lab-e-tiny-sparse-moe` | Four-expert top-2 MoE, auxiliary losses, routing metrics, dense comparison |
| 5 | `codex/lab-h-fp16-fp4` | FP16 AMP, FP4 E2M1 codec, block scales, packed W4A16 weights, precision ablation |
| 6 | `codex/algorithm-suite-freeze` | End-to-end gate, bilingual chapter/lab docs, final report, freeze, resume bullets |

The historical Chapter 1–3 branches are not rewritten. The new branches are
algorithm overlays whose canonical teaching homes remain Chapters 12, 13, 18
and Labs A, B, C, E, and H.

## Hardware-Bounded Default Model

The first mandatory configuration is intentionally small enough for the local
4 GB GPU:

```text
tokenizer: deterministic UTF-8 byte tokenizer
vocab_size: at most 512 including special tokens
hidden_size: 128
layers: 4
attention_heads: 4
kv_heads: 2 or 4
sequence_length: 128 initially, 256 only after memory gate
dense_intermediate_size: 384
experts: 4
experts_per_token: 2
micro_batch_size: 1-8, selected by measured peak memory
gradient_accumulation: used to reach the declared effective batch
loader_workers: 0 by default on Windows
```

Larger configs are optional evidence, not substitutes for the required small
reproducible run.

## Strict Stage Gates

### Gate 0 - Planning and baseline

Required:

- branch matrix and source decisions documented;
- current roadmap and architecture consistent;
- 168 existing tests pass;
- secrets remain untracked and unprinted;
- hardware and precision capabilities recorded;
- project Skill validates.

### Gate 1 - Trajectory and evidence evaluation

Required:

- schema validation: 100%;
- deterministic export hash for the same fixture: exact match;
- run/turn/event/tool/source/claim id linkage: 100%;
- secret and hidden-reasoning leakage: zero findings;
- Citation Precision and Recall: 1.00 on gold fixtures;
- Claim Support classification accuracy: 1.00 on deterministic gold fixtures;
- Contradiction Recall: 1.00 on deterministic gold fixtures;
- Abstention Accuracy: 1.00 on deterministic gold fixtures;
- existing tests plus new eval/evidence tests pass;
- JSON and Markdown reports are generated from the same result object.

### Gate 2 - Tiny dense model

Required:

- tensor-shape, causal-mask, padding-mask, gradient, and generation tests pass;
- all losses and gradients remain finite;
- fixed micro-corpus overfit loss falls by at least 30% from its initial measured
  value within the bounded gate run;
- checkpoint reload reproduces logits within declared tolerance;
- same seed reproduces the same CPU gate result;
- GPU smoke run stays below 3.5 GB peak allocated memory;
- run manifest records commit, config, data hash, seed, precision, hardware,
  checkpoint hash, and metrics.

### Gate 3 - Trajectory distillation

Required:

- Qwen and DeepSeek use the same bounded task manifest;
- teacher outputs are redacted public trajectories only;
- schema/tool/evidence validation, deduplication, and lineage checks: 100%;
- train/dev/test hashes are disjoint;
- hard-label SFT is the mandatory API-teacher path;
- KL distillation is used only with a local teacher sharing tokenizer/vocabulary;
- held-out tool decision accuracy improves over the untrained/pre-SFT student;
- no evidence-control metric regresses below the declared baseline;
- per-teacher and combined reports include failures, latency, tokens, and cost
  when providers return usage.

### Gate 4 - Tiny sparse MoE

Required:

- four experts and top-2 distinct routing are enforced;
- selected routing weights sum to one within tolerance;
- forward/backward and checkpoint tests pass;
- router auxiliary and z-loss values are finite;
- every expert receives traffic on the balanced routing fixture;
- maximum/minimum expert load ratio is at most 2.0 on that fixture;
- router entropy is reported and collapse detection is green;
- the same bounded training corpus shows at least a 30% loss reduction;
- dense and MoE comparisons use the same data, seed, steps, and scorer versions;
- total parameters, active parameters, estimated active FLOPs, throughput, and
  peak memory are reported.

### Gate 5 - FP16 and FP4

Required:

- real CUDA FP16 AMP forward/backward runs without non-finite values;
- FP16 checkpoint inference matches FP32 within a declared numeric tolerance;
- every representable E2M1 code round-trips exactly;
- nibble pack/unpack is bit-exact for odd and even tensor lengths;
- block scale metadata is versioned and validated;
- packed W4A16 storage, including scales, is at least 65% smaller than FP16
  weights for gated tensors;
- FP4 dequantized inference produces finite outputs;
- held-out loss/accuracy degradation is reported; if it breaches the configured
  quality gate, fake-quantization/QAT is attempted before the stage can pass;
- reports explicitly distinguish FP4 storage, dequantized W4A16 compute, and
  unavailable native FP4 compute.

### Gate 6 - Final freeze

Required:

- every earlier gate reruns from documented commands;
- full Python suite passes;
- no new frontend dependency exists;
- all generated numbers link to a manifest and machine-readable artifact;
- branch ancestry and commits match the stacked plan;
- Chinese and English lab documents match structure and technical claims;
- final implementation, experiment, limitations, and branch reports exist;
- freeze notes list implemented, measured, optional, and deferred work without
  overstating results;
- Agent development and algorithm bullets are added to the Obsidian resume source
  only after the final measurements exist.

## Failure Policy

1. Stop the current stage on the first failed mandatory gate.
2. Preserve logs and the failing manifest.
3. Diagnose and fix within the same stage.
4. Rerun the narrow gate, then the complete stage gate.
5. Advance only after both pass.
6. Never weaken a threshold merely to make the pipeline green. A threshold may
   change only when the metric definition was wrong, and the report must record
   the old value, new value, and evidence for the correction.

## Project Skill

Created and validated:

```text
C:\Users\jsj31\.codex\skills\agentladder-strict-completion\SKILL.md
C:\Users\jsj31\.codex\skills\agentladder-strict-completion\agents\openai.yaml
C:\Users\jsj31\.codex\skills\agentladder-strict-completion\references\gates.md
C:\Users\jsj31\.codex\skills\agentladder-strict-completion\references\branching.md
C:\Users\jsj31\.codex\skills\agentladder-strict-completion\scripts\audit_repo.py
```

Validation evidence:

- `quick_validate.py`: `Skill is valid!`
- audit script Python compilation: passed
- first Skill audit run: passed
- audit schema: `agentladder-readiness-v1`
- detected tests: 168
- full baseline suite return code: 0
- required canonical docs present: 5/5
- Qwen and DeepSeek teacher-key presence detected without exposing values
- CUDA/PyTorch/GPU/VRAM capability detected correctly
- audit artifact: `.tmp/algorithm-audit.json` (ignored local evidence)

## Planning Gate Result

Gate 0 is green. The roadmap, architecture rules, README/lab conventions,
branch plan, MiniMind reference decisions, hardware envelope, strict thresholds,
failure policy, and reusable Skill are aligned. The next allowed action is to
commit and push `codex/ch03-algorithm-roadmap`, then create
`codex/lab-a-evidence-eval` from that verified commit.
