# Paper Processing Plan — Chapter 3 Freeze

**Date:** 2026-05-31
**Total corpus target:** 116 papers (40 existing + 76 candidates)
**Chapter 3 freeze target:** 80–120 papers with overview, 60–80 with chunks, 20–30 with visuals

---

## Processing Tiers

### S-tier: Full Processing (43 candidates + 40 existing = 83 total)
Must have: PDF → MinerU → metadata + overview + fulltext + sections + chunks + visuals
All S-tier papers MUST be fully searchable via Chapter 3 providers.

### A-tier: Selective Processing (33 candidates)
Priority: overview + chunks; figures/tables only when valuable.
Lower priority papers may get overview_only if time-constrained.

### Watchlist: Metadata Only (1 candidate)
AlexNet — foundation paper, metadata entry only for historical completeness.

---

## Phase 1: Immediate (Chapter 3 Critical) — 25 papers

Papers directly supporting Agentic RAG / Controlled Research Runtime:

| paper_id | Title | Processing |
|----------|-------|------------|
| paper_049 | Transformer (Attention Is All You Need) | full_pdf |
| paper_055 | GPT-3 | full_pdf |
| paper_058 | InstructGPT / RLHF | full_pdf |
| paper_070 | Reflexion | full_pdf |
| paper_071 | REALM | full_pdf |
| paper_072 | DPR | full_pdf |
| paper_073 | FiD | full_pdf |
| paper_074 | ColBERT | full_pdf |
| paper_077 | HyDE | full_pdf |
| paper_078 | RAPTOR | full_pdf |
| paper_079 | LightRAG | full_pdf |
| paper_080 | FLARE | full_pdf |
| paper_082 | SWE-bench | full_pdf |
| paper_091 | AgentBench | full_pdf |
| paper_092 | GAIA | full_pdf |
| paper_094 | World Models (Ha & Schmidhuber) | full_pdf |
| paper_095 | DreamerV3 | full_pdf |
| paper_104 | CLIP | full_pdf |
| paper_108 | LLaVA | full_pdf |
| paper_109 | ColPali | full_pdf |
| paper_111 | DPO | full_pdf |
| paper_112 | Constitutional AI | full_pdf |
| paper_114 | Process Reward Models | full_pdf |
| paper_053 | BERT | full_pdf |
| paper_064 | Self-Consistency | full_pdf |

Status: These 25 are the highest priority for Chapter 3.

---

## Phase 2: Chapter 4–9 Foundation — 35 papers

Supporting Memory, Research Agent, Eval, RL chapters:

| paper_id | Title | Processing |
|----------|-------|------------|
| paper_044 | ResNet | full_pdf |
| paper_045 | Adam | full_pdf |
| paper_047 | Seq2Seq | full_pdf |
| paper_048 | Attention / NMT | full_pdf |
| paper_050 | ViT | full_pdf |
| paper_054 | T5 | full_pdf |
| paper_056 | Scaling Laws | full_pdf |
| paper_057 | Chinchilla | full_pdf |
| paper_059 | LLaMA | full_pdf |
| paper_060 | Switch Transformer | full_pdf |
| paper_061 | Mixtral | full_pdf |
| paper_062 | DeepSeek-V3 | full_pdf |
| paper_063 | DeepSeek-R1 | full_pdf |
| paper_065 | Least-to-Most Prompting | full_pdf |
| paper_066 | PAL | full_pdf |
| paper_068 | Graph of Thoughts | full_pdf |
| paper_075 | Contriever | full_pdf |
| paper_081 | WebArena | full_pdf |
| paper_083 | ToolLLM | full_pdf |
| paper_084 | CodeAct | full_pdf |
| paper_085 | OSWorld | full_pdf |
| paper_096 | MuZero | full_pdf |
| paper_097 | DDPM | full_pdf |
| paper_098 | Latent Diffusion Models | full_pdf |
| paper_099 | DiT | full_pdf |
| paper_101 | PointNet | full_pdf |
| paper_102 | NeRF | full_pdf |
| paper_103 | 3D Gaussian Splatting | full_pdf |
| paper_105 | Segment Anything | full_pdf |
| paper_107 | BLIP-2 | full_pdf |
| paper_113 | PPO | overview_only |
| paper_116 | MemoryBank | overview_only |
| paper_115 | MRKL | overview_only |
| paper_051 | GPT | overview_only |
| paper_052 | GPT-2 | overview_only |

---

## Phase 3: Lower Priority / Reference — 16 papers

| paper_id | Title | Processing |
|----------|-------|------------|
| paper_041 | AlexNet | metadata_only |
| paper_042 | VGG | overview_only |
| paper_043 | BatchNorm | full_pdf |
| paper_046 | Dropout | overview_only |
| paper_067 | Program of Thoughts | overview_only |
| paper_069 | Plan-and-Solve | overview_only |
| paper_076 | Atlas | overview_only |
| paper_086 | Mind2Web | overview_only |
| paper_087 | WebShop | overview_only |
| paper_088 | HELM | overview_only |
| paper_089 | MMLU | overview_only |
| paper_090 | BIG-Bench | overview_only |
| paper_093 | Prompt Injection | overview_only |
| paper_100 | Video Diffusion Models | overview_only |
| paper_106 | Flamingo | overview_only |
| paper_110 | RAG-Anything | overview_only |

---

## Per-Paper Action Checklist

For each full_pdf paper:
- [ ] Download PDF (arxiv or official open-access URL only)
- [ ] MinerU process → fulltext.txt + sections.json + figures/ + tables/ + pages/
- [ ] Generate metadata.json with bibliographic fields
- [ ] Generate overview.md with all template sections
- [ ] Generate chunks.jsonl (600–900 token chunks, 80–150 token overlap)
- [ ] Generate visuals.jsonl (captions, nearby_text, image_paths)
- [ ] Validate via `validate_paper_corpus.py --strict`
- [ ] Add to manifest.jsonl

For each overview_only paper:
- [ ] Generate metadata.json from manifest
- [ ] Generate overview.md from template
- [ ] Create empty chunks.jsonl and visuals.jsonl
- [ ] Validate

For each metadata_only paper:
- [ ] Generate metadata.json
- [ ] Record in manifest.jsonl with processing_status="metadata_only"

---

## Chapter 3 Freeze Guarantees

By freeze:
- 80–120 papers will have overview.md (40 existing + 40-80 new)
- 60–80 papers will have chunks.jsonl (40 existing + 20-40 new full_pdf)
- 20–30 papers will have visuals.jsonl with figures/tables (existing 36 + new)
- All S-tier papers will be searchable via BM25 keyword providers
- All papers will pass `validate_paper_corpus.py --strict`
