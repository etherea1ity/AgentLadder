# Chapter 2: RAG Agent — Klara's Sun Library

Chapter 2 upgrades Klara from a Minimal Agent into a small local-knowledge RAG Agent.

The chapter goal is not to build a production search platform. The goal is to make every step visible and teachable:

```text
Markdown + Metadata
→ Document
→ TextChunk
→ IndexRecord
→ Embedding
→ Dense Retrieval + BM25
→ Hybrid Retrieval
→ Reranking
→ Context Builder
→ Klara Writer
→ AnswerFrameV1
→ Run Chain / Trace
```

## What Klara can do in v0.2

Klara can now:

1. read local Markdown knowledge with sidecar metadata;
2. split documents into overlap chunks;
3. build local JSONL `IndexRecord` entries with dense vectors and sparse tokens;
4. route questions through an LLM JSON intent router with deterministic fallback;
5. retrieve candidates with dense cosine search and BM25;
6. fuse retrieval results with weighted hybrid scoring;
7. rerank candidates with transparent rule signals;
8. build a writer-ready evidence context;
9. answer with a lightweight `AnswerFrameV1` containing question, answer, and evidence;
10. show public module cards in the right-side Run Chain.

## Core code map

```text
src/agent_ladder/rag/contracts/          # Document, TextChunk, AnswerFrame, source/module contracts
src/agent_ladder/rag/ingestion/          # LocalMarkdownLoader
src/agent_ladder/rag/chunking/           # OverlapTextSplitter
src/agent_ladder/rag/embeddings/         # Embedder interface + DashScope implementation
src/agent_ladder/rag/indexing/           # IndexRecord, local JSONL index, vector search
src/agent_ladder/rag/retrieval/          # Dense, BM25, hybrid retrieval
src/agent_ladder/rag/reranking/          # SimpleReranker
src/agent_ladder/rag/context/            # ContextBuilder
src/agent_ladder/rag/routing/            # IntentRouter + fallback rule router
src/agent_ladder/rag/writer/             # Klara writer prompts
src/agent_ladder/core/runtime/klara_agent.py
apps/api/services/run_service.py         # API run lifecycle + module emission
apps/web/src/components/RunMargin.tsx    # Run Chain UI entry
apps/web/src/components/klara/           # Klara presence UI
```

## Local knowledge library

The first knowledge set is intentionally small:

```text
data/knowledge/global/klara-overview.md
data/knowledge/chapters/ch01-minimal-agent.md
data/knowledge/chapters/ch02-rag-agent.md
```

Each Markdown file has a sibling `.metadata.yaml` file so retrieval and citation layers can preserve identity, chapter, version, tags, and summary.

## Run it

```powershell
# Build the local JSONL RAG index
py scripts/rag/build_index.py

# Start backend and frontend
powershell -ExecutionPolicy Bypass -File .\start.ps1 -NoOpen

# Open the UI
# http://127.0.0.1:5123
```

Example RAG questions:

```text
Tell me about chapter 2.
What did Klara learn in chapter one?
What is AnswerFrameV1?
```

## Boundaries

v0.2 deliberately stays simple:

- local JSONL index, not a production vector database;
- LLM JSON router with deterministic fallback, not a trained router model;
- simple BM25 and weighted hybrid fusion;
- rule-based reranker, not cross-encoder or LLM judge;
- source and citation contracts, but no citation verifier;
- no query rewrite, retrieval planning, evidence grader, or state-machine loop yet.

Those belong to `v0.3-agentic-rag`.
