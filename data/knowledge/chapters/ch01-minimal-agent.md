# Chapter 1 Capability: Minimal Agent

## Knowledge Status

This document is part of Klara's local knowledge library. It summarizes the first chapter of Agent Ladder: `v0.1-minimal-agent`.

Klara should use this document when a user asks what Klara learned in Chapter 1, what Minimal Agent means, why a single API call is not yet an agent, what `AskState`, `AnswerState`, `RunLog`, or JSONL trace mean, or what Klara could and could not do in v0.1.

## Chapter Goal

In `v0.1-minimal-agent`, Klara learns her first runnable agent loop.

The chapter goal is to start from one real LLM API call and wrap it in a minimal structure that is stateful, configurable, testable, and observable.

The core chain is:

```text
Question
→ AskState
→ LLM Call
→ AnswerState
→ RunLog
→ JSONL Trace
```

This chapter is not about building a complex multi-tool system. It is about making the smallest useful agent run visible.

## What Klara Can Do in v0.1

Klara v0.1 can receive a user question, create structured input state, call a real LLM provider, produce a structured answer state, record a run log, count tokens, and save a trace.

Klara's v0.1 abilities include:

- receiving a user question
- creating `AskState` as structured input
- calling a real DashScope / OpenAI-compatible LLM provider
- streaming an answer to the frontend
- creating `AnswerState` as structured output
- creating `RunLog` with run id, ask id, model, latency, input tokens, output tokens, total tokens, error state, and timestamps
- saving a JSONL trace
- showing a minimal run chain in the UI
- separating the agent core from the backend API and frontend UI
- preserving a teaching-friendly code path that learners can inspect

## Why an API Call Is Not Yet an Agent

A raw LLM API call can take a message and return a message. This is useful, but it is not enough to teach agent architecture.

A raw call does not necessarily record what the user asked as structured state. It does not necessarily record what model was used, how long the call took, how many tokens were consumed, whether an error occurred, or where the result was saved. It may produce text, but it does not automatically create an observable run.

A minimal agent adds a harness around the model call.

The harness creates input state, calls the model through a provider interface, creates output state, records observability data, and writes a trace. This turns a one-time call into a run that can be inspected, tested, and improved.

In Chapter 1, Klara learns this difference:

```text
LLM API Call = input text → output text
Minimal Agent Run = input state → model call → output state → run log → trace
```

## AskState

`AskState` represents the user's question as structured input.

It can include an ask id, the question text, language information, and a creation timestamp. The important idea is that Klara does not treat the user input as a loose string floating through the system. She turns it into a named state object.

`AskState` is the first sign that a run has structure.

A useful explanation is:

```text
AskState = what the user asked, recorded as state
```

This matters because future branches will add more state objects. In RAG, retrieval queries and retrieval results become state. In Agentic RAG, evidence items and evidence packs become state. In memory, selected sources and previous answers become state.

## AnswerState

`AnswerState` represents what Klara answered.

It can include the ask id, answer text, model name, and creation timestamp. In v0.1, the answer is mostly a string. In later branches, this grows into richer answer structures such as `AnswerFrame`, which can include sources, citations, insufficient-evidence flags, and other metadata.

A useful explanation is:

```text
AnswerState = what Klara answered, recorded as state
```

This object makes it clear that the output of an agent run is not only text. It is also part of the run record.

## RunLog

`RunLog` records what happened during the run.

It can include:

- run id
- ask id
- model name
- latency
- input token count
- output token count
- total token count
- error message
- creation timestamp
- completion timestamp

A useful explanation is:

```text
RunLog = the observable record of this run
```

RunLog is important because learners should be able to ask: which model did Klara call, how long did it take, how many tokens did it use, and did anything fail?

Tokens can be understood as part of Klara's operating energy. Counting tokens is not only a billing concern. It also teaches that agent runs have cost, budget, and performance constraints.

## JSONL Trace

JSONL trace is the persisted record of the run.

In v0.1, Klara saves trace data in JSONL format so each run can be inspected later. JSONL is simple, append-friendly, and easy to read during early teaching stages.

A useful explanation is:

```text
Trace = the saved memory of how this run happened
```

Trace is the beginning of future evaluation and policy improvement. Later branches can use traces to build eval datasets, analyze failures, compare strategies, and improve routing or retrieval behavior.

## MinimalAgent Runtime

`MinimalAgent` coordinates the v0.1 run.

Its responsibility is small and clear:

```text
receive question
→ create AskState
→ call LLMClient
→ create AnswerState
→ create RunLog
→ save trace
→ return answer
```

`MinimalAgent` should not become a large class that contains every future feature. Later branches should add new runtime objects, such as `RagAgent`, while keeping the minimal agent understandable.

## User Interface and Run Margin

The v0.1 UI is designed to show that one answer is also one observable run.

Klara can display the user message, stream the assistant answer, and show a run chain in the right-side Run Margin. The Run Margin does not expose raw chain-of-thought. It shows safe public activity: model call, latency, token counts, status, and trace information.

This distinction is important. Agent Ladder wants to teach observability without leaking private reasoning.

## Why Chapter 1 Matters for RAG

Chapter 1 creates the foundation that RAG needs.

RAG will add retrieval, chunks, context, sources, and citations. But these features still need the same minimal foundation: input state, runtime coordination, model calls, run logs, and trace persistence.

Without Chapter 1, RAG would be a pile of retrieval functions. With Chapter 1, RAG becomes an observable agent run.

## What Klara Cannot Do Yet in v0.1

Klara v0.1 cannot read local documents, retrieve knowledge, cite sources, search the web, remember previous sessions as long-term memory, use MCP tools, evaluate her own answers, or optimize policies.

If a user asks Klara v0.1 about local project documents, she can only answer from model knowledge and prompt context. She does not yet have a local knowledge library.

These limitations are intentional. They make the first chapter small enough to understand.
