# Chapter 2 Capability: RAG Agent

## Knowledge Status

This document is part of Klara's local knowledge library. It summarizes the second chapter of Agent Ladder: `v0.2-rag-agent`.

Klara should use this document when a user asks why RAG is needed, what Klara's Sun Library is, what external knowledge means, how RAG reduces hallucination, what `Document`, `Chunk`, `Embedding`, `Index`, `Retriever`, `SourceCard`, `Citation`, or `AnswerFrame` mean, or what is excluded from v0.2.

## Chapter Goal

In `v0.2-rag-agent`, Klara learns how to read from her first local knowledge library.

The local knowledge library is called:

```text
Klara's Sun Library
```

The core chain is:

```text
Question
→ Retrieve Local Knowledge
→ Build Context
→ LLM
→ Grounded Answer
→ Sources / Citations
→ RunLog / Trace
```

This chapter turns Klara from a direct-answer minimal agent into a local-knowledge RAG agent.

## Why Klara Needs RAG

In Chapter 1, Klara can answer by calling an LLM. That is useful, but it means the answer depends mainly on the model's parameters and prompt context.

Model knowledge is not the same as project knowledge. The model may understand general ideas such as agents, RAG, vector search, or citation, but it does not automatically know the latest local README, roadmap, chapter notes, product documents, or paper notes.

RAG gives Klara an external knowledge layer.

A useful explanation is:

```text
RAG = Retrieval-Augmented Generation
RAG = use retrieved external knowledge to improve generation
```

Instead of answering only from memory, Klara first looks into her local library, retrieves relevant passages, builds context, and then asks the model to answer with that context.

## External Knowledge

External knowledge means information that is outside the model parameters.

For Klara, the first external knowledge is not the internet. It is a small local library of markdown documents about Klara and Agent Ladder.

External knowledge matters because it can be updated. The local library can change every day. New chapter notes, new roadmap details, and new design records can be added without retraining the model.

In v0.2, Klara learns to use this external knowledge through local RAG.

## Traceability

A normal model response can sound fluent but leave the user unable to inspect where the information came from.

RAG should make answers more traceable. Klara should be able to show which documents or chunks contributed to the answer.

Traceability depends on objects such as:

- `Document`
- `TextChunk`
- `SourceCard`
- `Citation`
- `AnswerFrame`
- run trace events

A useful explanation is:

```text
Traceability = the ability to go from an answer back to the sources that supported it
```

This is one reason v0.2 introduces source and citation structures.

## Hallucination Reduction

LLMs can generate fluent but unsupported content when evidence is missing. This is often called hallucination.

RAG cannot completely eliminate hallucination, but it can reduce hallucination risk by giving the model relevant context and by encouraging grounded answers.

Klara should follow this principle:

```text
Do not answer only from memory when local evidence is required.
Retrieve first.
Use the retrieved context.
If the local library does not contain enough evidence, say that the evidence is insufficient.
```

In v0.2, Klara should prefer an honest insufficient-evidence answer over an unsupported confident answer.

## Klara's Sun Library

Klara's Sun Library is the first local knowledge library for Klara.

It starts small on purpose. The first library should contain a few markdown documents that explain Klara's identity, Agent Ladder's learning path, Chapter 1 capabilities, and Chapter 2 RAG capabilities.

The first library is not a production knowledge base. It is a teaching library. Its job is to make the RAG pipeline visible and understandable.

The first documents can include:

```text
data/knowledge/global/klara-overview.md
data/knowledge/chapters/ch01-minimal-agent.md
data/knowledge/chapters/ch02-rag-agent.md
```

These documents let Klara answer questions such as:

- Who is Klara?
- What is Agent Ladder?
- What did Klara learn in Chapter 1?
- What is Klara learning in Chapter 2?
- What abilities belong to future branches?

## v0.2 Standard RAG Flow

The v0.2 flow should remain standard and minimal:

```text
Markdown File
→ Document Loader
→ Text Cleaning
→ Metadata
→ Document
→ Chunking
→ Embedding
→ Vector Index
→ Retriever
→ Context Builder
→ LLM
→ AnswerFrame
→ Sources / Citations
→ Trace
```

This is intentionally not full Agentic RAG. The goal is to build the reusable foundation first.

## Document Loader

A markdown file on disk is not yet a RAG system object.

The Document Loader turns local files into `Document` objects.

A useful explanation is:

```text
File → Document
```

A `Document` should contain text and metadata. The loader gives Klara a stable way to bring external knowledge into the system.

The first loader can be simple. It only needs to load local `.md` and `.txt` files from `data/knowledge`. Future branches can add loaders for PDF, HTML, webpages, or other formats.

## Text Cleaning

Text cleaning makes loaded text stable before chunking and embedding.

Text cleaning is not summarization and not rewriting. It should not change the meaning of the source. It only normalizes the text so later steps behave consistently.

The first cleaning rules can include:

- normalize line endings
- trim leading and trailing whitespace
- collapse excessive blank lines
- preserve markdown headings
- preserve code blocks

Clean text makes chunking more predictable and retrieval easier to test.

## Metadata Design

Metadata is the identity card of a document.

Without metadata, Klara may retrieve a useful passage but fail to explain where it came from. With metadata, Klara can say which source document, category, chapter, or branch supported an answer.

A minimal metadata structure can include:

- source path
- title
- category
- chapter
- version
- tags

Metadata is the foundation for `SourceCard` and `Citation`.

## Chunking

Klara should not retrieve entire long documents as one unit.

Chunking splits documents into smaller text pieces that can be embedded and retrieved.

A useful explanation is:

```text
Document → TextChunk[]
```

Chunks should be large enough to preserve meaning but small enough to retrieve precisely. v0.2 can begin with a simple fixed-size splitter and overlap. More advanced semantic splitting can come later.

## Embedding

Embedding turns text into vectors.

A useful explanation is:

```text
TextChunk.text → vector
```

Similar text should have similar vector representations. This lets the retriever compare a user question with stored chunks.

In v0.2, embedding should be provider-based and configurable. The model name should live in configuration, not be hard-coded inside the retrieval logic.

## Vector Index

The vector index stores chunks and their vectors so Klara can search them.

A simple local index is enough for v0.2. It can store chunks and embeddings in JSONL files under `data/indexes`.

A useful explanation is:

```text
TextChunk + vector → searchable index
```

v0.2 does not need a production database or hosted vector store. A readable local index is better for teaching.

## Retriever

The retriever finds chunks that are relevant to a user question.

A useful explanation is:

```text
Question → RetrievalQuery → RetrievalResult[]
```

v0.2 can start with dense retrieval and then add a simple BM25 or hybrid retrieval step. Hybrid retrieval combines vector similarity with keyword matching. This gives learners a more standard RAG foundation than vector-only search.

## Context Builder

The context builder turns retrieved chunks into a compact context for the LLM.

The model should not receive the whole knowledge library. It should receive a small, relevant context built from retrieval results.

A useful explanation is:

```text
RetrievalResult[] → context string for the LLM
```

The context builder should preserve source labels so the final answer can cite them.

## SourceCard and Citation

`SourceCard` is a readable description of a source used in an answer.

`Citation` is a reference from the answer back to a source or chunk.

These objects make Klara's answer more traceable. A user should be able to see which documents supported the answer.

A useful explanation is:

```text
SourceCard = where the information came from
Citation = how the answer points back to that source
```

## AnswerFrame

`AnswerFrame` is a structured answer.

In Chapter 1, Klara mostly returns answer text. In Chapter 2, the answer should begin to include answer mode, sources, citations, and evidence sufficiency.

A minimal `AnswerFrame` can include:

- answer text
- mode, such as `direct` or `rag`
- sources
- citations
- insufficient evidence flag

This creates a bridge from simple answers to future evidence-based answers.

## v0.2 Boundary

Klara v0.2 does not yet perform full Agentic RAG.

She does not yet rewrite queries, plan multi-step retrieval, grade evidence, run retrieval loops, verify citations deeply, combine local RAG with web search, produce long-form research reports, or use memory to resolve follow-up references.

Those abilities belong to later branches.

In v0.2, Klara should be honest when the local library is insufficient. She should say that the local knowledge does not contain enough evidence instead of inventing unsupported details.
