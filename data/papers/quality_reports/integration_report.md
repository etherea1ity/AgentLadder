# Chapter 3 Real Corpus Integration Report

## Query: 给我 10 篇 Agentic RAG 相关论文，并按路线分类

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 6
- source_count: 10
- evidence_items: 20
- visual_sources: 0
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 10631
- trace_saved: True

## Query: Explain Self-RAG in Chinese.

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 6
- source_count: 2
- evidence_items: 2
- visual_sources: 0
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 7574
- trace_saved: True

## Query: Compare ReAct, Reflexion, and Voyager.

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 6
- source_count: 10
- evidence_items: 10
- visual_sources: 0
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 10838
- trace_saved: True

## Query: Find papers about retrieval control and query rewriting.

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 6
- source_count: 10
- evidence_items: 10
- visual_sources: 0
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 8805
- trace_saved: True

## Query: Explain figure-aware RAG in Chinese, include figure if available.

- route: rag
- run_mode: agentic_rag
- search_units: 4
- retrieval_attempts: 7
- source_count: 10
- evidence_items: 10
- visual_sources: 1
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 8819
- trace_saved: True

## Query: 找几篇 world model / spatial world model 相关论文。

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 6
- source_count: 10
- evidence_items: 10
- visual_sources: 0
- evidence_status: sufficient
- verification_status: passed
- latency_ms: 8882
- trace_saved: True

## Query: This query should not match anything: qwerty_nonexistent_agent_ladder_topic

- route: rag
- run_mode: agentic_rag
- search_units: 3
- retrieval_attempts: 10
- source_count: 0
- evidence_items: 0
- visual_sources: 0
- evidence_status: insufficient
- verification_status: passed
- latency_ms: 2496
- trace_saved: True

## Next Fixes

- Review failed or weak queries and improve metadata/chunks rather than weakening verifier.
