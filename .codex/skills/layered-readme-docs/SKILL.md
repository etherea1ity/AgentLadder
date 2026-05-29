---
name: layered-readme-docs
description: Use when writing or refactoring Agent Ladder/Klara chapter README sections so the visible README stays as a learning roadmap while detailed concepts, algorithms, formulas, examples, and engineering tradeoffs live inside Markdown <details> blocks.
---

# Layered README Docs

Use this skill for Agent Ladder / Klara teaching README work, especially chapter sections that mix product flow, code paths, math, and algorithms.

## Core rule

Separate the README into two layers:

- **Outer layer:** answers “What does Klara do in this step?”
- **`<details>` layer:** answers “Why does this technology/algorithm work this way?”

## Outer layer must stay short

For each section, keep only these five things visible:

1. What problem this section solves.
2. Input.
3. Output.
4. What Klara learns / gains at this step.
5. Corresponding code paths.

Use a compact flow block:

```text
Input
→ Process
→ Output
```

## Details layer content

Put lecture-style material inside `<details>`:

- concept background
- classic algorithms
- examples
- math formulas
- engineering tradeoffs
- why this implementation was chosen
- common pitfalls
- future upgrades

Preferred pattern:

````md
### X. Title: one-line purpose

1-2 short paragraphs of visible roadmap text.

```text
Input
→ Process
→ Output
```

Klara learns: ...

Corresponding code:

```text
src/...
```

<details>
<summary>Expand: principles, classic methods, and this chapter's implementation</summary>

Detailed lecture content here.

</details>
````

## Placement guide

- Metadata outer: why metadata is needed; input/output; fields; code paths.
- Metadata details: versioning, filtering, source cards, source identity design.
- Chunking outer: why chunk; chosen overlap strategy; input/output; code paths.
- Chunking details: fixed-size, recursive, heading-based, semantic, overlap comparison.
- IndexRecord outer: why TextChunk should not carry retrieval state; boundary; code path.
- IndexRecord details: Qdrant point, Weaviate object, Elasticsearch doc analogies.
- Embedding outer: text to vector; chunk/query both embedded; code paths.
- Embedding details: vocabulary, one-hot, bag of words, sparse vector, dense vector, cosine similarity, model choice.
- Vector Index outer: store vectors and search; JSONL/local index; code paths.
- Vector Index details: cosine implementation, brute-force search, FAISS/Qdrant/Milvus/HNSW overview.
- BM25 outer: keyword retrieval for exact names and project terms.
- BM25 details: TF, IDF, length normalization, BM25 formula.
- Hybrid outer: dense + sparse fusion.
- Hybrid details: score fusion, normalization, RRF, weight tradeoffs.
- Reranking outer: choose final chunks for prompt.
- Reranking details: rules, cross-encoder, LLM rerank, evidence grader.

## Style

- Use Chinese prose for this repository README unless asked otherwise.
- Keep the outer layer readable without expanding any details.
- Do not hide code paths in details; code paths belong in the outer layer.
- Do not put long formulas in the outer layer.
