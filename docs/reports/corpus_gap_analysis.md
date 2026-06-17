# Corpus Gap Analysis — Agent Ladder Chapter 3

**Date:** 2026-05-31
**Current:** 40 papers across ~10 directions
**Target:** 150–200 papers across 16 directions

---

## Direction 00: Deep Learning / Vision / NLP Foundation
**Current:** 0 papers ⚠️ EMPTY
**Target:** 10 papers

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | AlexNet (Krizhevsky et al., 2012) | must_have | CNN foundation |
| S | ResNet (He et al., 2015) | must_have | Deep residual learning |
| S | BatchNorm (Ioffe & Szegedy, 2015) | must_have | Training stability |
| S | Adam (Kingma & Ba, 2014) | must_have | Optimizer |
| S | Dropout (Srivastava et al., 2014) | must_have | Regularization |
| S | Seq2Seq (Sutskever et al., 2014) | must_have | Sequence learning |
| S | Attention / NMT (Bahdanau et al., 2014) | must_have | Attention mechanism |
| S | Transformer (Vaswani et al., 2017) | must_have | Foundation of all modern LLMs |
| A | ViT (Dosovitskiy et al., 2020) | should_have | Vision transformer |
| A | VGG (Simonyan & Zisserman, 2014) | nice_to_have | Classical vision |

---

## Direction 00a: Transformer / LLM Base
**Current:** 0 papers ⚠️ EMPTY
**Target:** 14 papers

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | GPT (Radford et al., 2018) | must_have | First generative pre-trained transformer |
| S | GPT-2 (Radford et al., 2019) | must_have | Scaling language models |
| S | BERT (Devlin et al., 2018) | must_have | Bidirectional encoder |
| S | T5 (Raffel et al., 2019) | must_have | Text-to-text framework |
| S | GPT-3 (Brown et al., 2020) | must_have | Few-shot learning at scale |
| S | Scaling Laws (Kaplan et al., 2020) | must_have | Compute-optimal scaling |
| S | Chinchilla (Hoffmann et al., 2022) | must_have | Optimal compute allocation |
| S | InstructGPT / RLHF (Ouyang et al., 2022) | must_have | Alignment foundation |
| S | LLaMA (Touvron et al., 2023) | must_have | Open-source LLM family |
| A | Switch Transformer (Fedus et al., 2021) | should_have | MoE at scale |
| A | Mixtral (Jiang et al., 2024) | should_have | Sparse MoE |
| A | DeepSeek-V3 (DeepSeek, 2024) | should_have | Frontier open LLM |
| A | DeepSeek-R1 (DeepSeek, 2025) | should_have | Reasoning via RL |
| A | Qwen3 / Kimi K2 | frontier | Latest open models |

---

## Direction 01: Agent Basic Paradigms
**Current:** 6 papers — Medium gap to 14 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| A | MRKL (Karpas et al., 2022) | should_have | Modular reasoning |
| A | AutoGPT / BabyAGI analysis | should_have | Autonomous agent design |
| A | Voyager (Wang et al., 2023) | must_have | Lifelong learning (already paper_022!) |

**Assessment:** This direction is reasonably covered by existing surveys.

---

## Direction 02: Prompting / Reasoning
**Current:** 2 papers — Large gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | Self-Consistency (Wang et al., 2022) | must_have | Improves CoT |
| S | Least-to-Most Prompting (Zhou et al., 2022) | must_have | Decomposition |
| A | PAL (Gao et al., 2022) | should_have | Program-aided language |
| A | Program of Thoughts (Chen et al., 2022) | should_have | Code as reasoning |
| A | Graph of Thoughts (Besta et al., 2023) | should_have | Graph reasoning |
| A | Plan-and-Solve (Wang et al., 2023) | should_have | Planning |
| A | Reflexion (Shinn et al., 2023) | should_have | Verbal RL |

---

## Direction 03: Retrieval / RAG Base
**Current:** 3 papers — Large gap to 12 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | REALM (Guu et al., 2020) | must_have | Retrieval-augmented LM |
| S | DPR (Karpukhin et al., 2020) | must_have | Dense passage retrieval |
| S | FiD (Izacard & Grave, 2020) | must_have | Fusion-in-Decoder |
| A | ColBERT (Khattab & Zaharia, 2020) | should_have | Late interaction |
| A | Contriever (Izacard et al., 2021) | should_have | Unsupervised dense retrieval |
| A | Atlas (Izacard et al., 2022) | should_have | Retrieval-augmented LM |
| A | HyDE (Gao et al., 2022) | should_have | Hypothetical document embeddings |
| A | RAPTOR (Sarthi et al., 2024) | should_have | Recursive summarization |
| A | LightRAG (Guo et al., 2024) | should_have | Graph-based RAG |

---

## Direction 04: Agentic RAG
**Current:** 6 papers — Close to target of 12

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | FLARE (Jiang et al., 2023) | must_have | Active retrieval |
| A | RAG-Fusion (Rackauckas, 2023) | should_have | Query fusion |
| A | Adaptive RAG papers | should_have | Adaptive retrieval pipeline |
| A | Query rewriting papers | should_have | Query optimization |
| A | Multi-agent RAG papers | should_have | Agent + RAG |

---

## Direction 05: Agent Architecture / Runtime
**Current:** 5 papers — Medium gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| A | LangGraph (LangChain, 2024) | should_have | Stateful agent runtime (technical report) |
| A | OpenAI Agents SDK docs | should_have | Tracing, guardrails, handoffs |
| A | Claude Code / Agent SDK docs | should_have | Agent architecture, tools |
| A | OpenClaw architecture | should_have | Gateway agent runtime |
| A | Agent protocol survey | should_have | Communication standards |

---

## Direction 06: Tool Use / Code Agent
**Current:** 3 papers — Large gap to 13 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | WebArena (Zhou et al., 2023) | must_have | Web agent benchmark |
| S | SWE-bench (Jimenez et al., 2023) | must_have | Software engineering benchmark |
| A | ToolBench / ToolLLM (Qin et al., 2023) | should_have | Tool learning |
| A | CodeAct (Wang et al., 2024) | should_have | Code as action |
| A | OSWorld (Xie et al., 2024) | should_have | OS environment |
| A | Mind2Web (Deng et al., 2023) | should_have | Web navigation |
| A | WebShop (Yao et al., 2022) | should_have | Web shopping environment |
| A | OpenHands / OpenDevin | should_have | Open coding agent |
| A | SWE-bench Multimodal | frontier | Multimodal coding |

---

## Direction 07: Memory / Reflection
**Current:** 6 papers — Small gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| A | MemoryBank (Zhong et al., 2023) | should_have | Long-term memory |
| A | Memento (Li et al., 2024) | should_have | Memory architecture |
| A | Skill library papers | should_have | Agent skill learning |

**Assessment:** Well-covered. Mostly needs depth in skill learning.

---

## Direction 08: Deep Research
**Current:** 6 papers — Small gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| A | Search-augmented reasoning (e.g., STaR, ReST) | should_have | Reasoning + search |
| A | Learning to Reason with Search | should_have | Search as reasoning |
| A | Multi-hop QA / research agents | should_have | Complex reasoning |
| A | Agentic reasoning with tools | should_have | Agent + tools + reasoning |

---

## Direction 09: Eval / Benchmark / Safety
**Current:** 0 papers ⚠️ EMPTY
**Target:** 13 papers

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | HELM (Liang et al., 2022) | must_have | Holistic evaluation |
| S | MMLU (Hendrycks et al., 2020) | must_have | Multi-task language understanding |
| S | BIG-Bench (2022) | must_have | Beyond imitation |
| S | AgentBench (Liu et al., 2023) | must_have | Agent evaluation |
| A | GAIA (Mialon et al., 2023) | should_have | General AI assistant |
| A | WebArena (Zhou et al., 2023) | must_have | Also in tool use |
| A | SWE-bench (Jimenez et al., 2023) | must_have | Also in tool use |
| A | ToolBench (Qin et al., 2023) | should_have | Tools |
| A | Prompt injection papers | should_have | Security |
| A | RAG hallucination / faithfulness | should_have | Citation quality |
| A | OSWorld | should_have | OS benchmark |

---

## Direction 10: World Models
**Current:** 5 papers — Medium gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | World Models (Ha & Schmidhuber, 2018) | must_have | Foundational world model |
| S | DreamerV3 (Hafner et al., 2023) | must_have | RL world model |
| A | PlaNet (Hafner et al., 2019) | should_have | Model-based RL |
| A | DreamerV2 (Hafner et al., 2020) | should_have | Discrete world model |
| A | MuZero (Schrittwieser et al., 2019) | should_have | Planning |
| A | JEPA (LeCun, 2022) | should_have | Predictive world model |
| A | Genie / Genie 3 (DeepMind, 2024) | frontier | Generative interactive environments |

---

## Direction 11: Video / Simulation / Generative World Model
**Current:** 0 papers ⚠️ EMPTY
**Target:** 8 papers

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | DDPM (Ho et al., 2020) | must_have | Diffusion foundation |
| S | Latent Diffusion Models (Rombach et al., 2022) | must_have | Stable diffusion |
| A | DiT (Peebles & Xie, 2023) | should_have | Diffusion transformers |
| A | Video Diffusion Models (Ho et al., 2022) | should_have | Video generation |
| A | Sora technical report (OpenAI, 2024) | frontier | Video world simulator |
| A | GAIA-1 (Wayve, 2023) | should_have | Driving world model |
| A | Video generation as world simulator | should_have | World simulation |

---

## Direction 12: 3D / Spatial Intelligence
**Current:** 4 papers — Medium gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | PointNet (Qi et al., 2017) | must_have | 3D point cloud |
| S | NeRF (Mildenhall et al., 2020) | must_have | Neural radiance fields |
| S | 3D Gaussian Splatting (Kerbl et al., 2023) | must_have | Real-time rendering |
| A | D-NeRF (Pumarola et al., 2020) | should_have | Dynamic NeRF |
| A | PointNet++ (Qi et al., 2017) | should_have | Hierarchical |
| A | WorldCraft / LatticeWorld | should_have | 3D world engines |

---

## Direction 13: Multimodal / VLM / Figure-Aware RAG
**Current:** 0 papers ⚠️ EMPTY
**Target:** 12 papers

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | CLIP (Radford et al., 2021) | must_have | Vision-language |
| S | ViT (Dosovitskiy et al., 2020) | must_have | Vision transformer |
| S | Segment Anything (Kirillov et al., 2023) | must_have | Segmentation |
| A | Flamingo (Alayrac et al., 2022) | should_have | Visual language model |
| A | BLIP-2 (Li et al., 2023) | should_have | Querying transformer |
| A | LLaVA (Liu et al., 2023) | should_have | Visual instruction tuning |
| A | GPT-4V report (OpenAI, 2023) | should_have | Vision capabilities |
| A | ColPali (Faysse et al., 2024) | should_have | Visual document retrieval |
| A | RAG-Anything | should_have | Multimodal RAG |
| A | ChartQA / DocVQA papers | should_have | Document understanding |

---

## Direction 14: RL / Alignment / Preference
**Current:** 2 papers — Large gap to 10 target

| Tier | Missing Paper | Priority | Notes |
|------|--------------|----------|-------|
| S | DPO (Rafailov et al., 2023) | must_have | Direct preference optimization |
| S | Constitutional AI (Bai et al., 2022) | must_have | Harmlessness training |
| A | PPO (Schulman et al., 2017) | should_have | RL foundation |
| A | GRPO papers | should_have | Group relative policy opt |
| A | Process Reward Models (Lightman et al., 2023) | should_have | Step-level rewards |
| A | Verifier-guided reasoning | should_have | Verified reasoning |
| A | Agent policy optimization | should_have | Agent-specific RL |

---

## Totals

| Direction | Current | Target Add | New Total |
|-----------|---------|-----------|-----------|
| 00 DL/CV/NLP | 0 | 10 | 10 |
| 00a Transformer/LLM | 0 | 14 | 14 |
| 01 Agent Paradigms | 6 | 3 | 9 |
| 02 Prompting/Reasoning | 2 | 7 | 9 |
| 03 Retrieval/RAG | 3 | 9 | 12 |
| 04 Agentic RAG | 6 | 5 | 11 |
| 05 Agent Architecture | 5 | 5 | 10 |
| 06 Tool Use/Code Agent | 3 | 9 | 12 |
| 07 Memory/Reflection | 6 | 3 | 9 |
| 08 Deep Research | 6 | 4 | 10 |
| 09 Eval/Benchmark | 0 | 13 | 13 |
| 10 World Models | 5 | 5 | 10 |
| 11 Video/Simulation | 0 | 8 | 8 |
| 12 3D/Spatial | 4 | 6 | 10 |
| 13 Multimodal/VLM | 0 | 12 | 12 |
| 14 RL/Alignment | 2 | 8 | 10 |
| **TOTAL** | **48 (40)** | **121** | **169** |

*Note: Some papers cross domains so total unique < sum of per-direction counts. 40 unique papers currently.*
