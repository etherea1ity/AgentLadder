# Tree of Thoughts: Deliberate Problem Solving with Large Language Models

YEAR: 2023
VENUE: NeurIPS 2023
URL: https://arxiv.org/abs/2305.10601
PDF_URL: https://arxiv.org/pdf/2305.10601.pdf
ARXIV_ID: 2305.10601
DOMAIN: reasoning, planning
METHOD_TAGS: tree-search, planning, deliberate-reasoning, BFS, DFS
BENCHMARKS: MATH

## One Sentence Summary

Language models are increasingly being deployed for general problem solving across a wide range of tasks, but are still confined to token-level, left-to-right decision-making processes during inference. This means they can fall short in tasks that require exploration, strategic lookahead, or where i

## Why It Matters



## Core Idea

[Auto-generated overview — to be refined with LLM]

## Method

Key methodological approach from 57 text chunks across the paper.

## Experiments

Benchmarks evaluated: MATH

## Limitations

[To be populated from paper analysis]

## Useful For These Questions

- What is the core contribution of Tree of Thoughts?
- How does this paper relate to Agent Ladder?
- What are the key methodological innovations?

## Key Figures

- Schematic illustrating various approaches to problem solving with LLMs. Each rec
- illustrates, while
- (c)). ToT frames any problem as a search
- ):
- ; Crosswords,
- ): [z(1), · · · , z(k)] ∼ppropose
- ). (2) Modularity. The base LM, as well as the thought decomposition,
- ToT in a game of 24. The LM is prompted for (a) thought generation and (b) valua
- (a), at each tree node, we exact the remaining
- (b), we prompt LM to evaluate each thought candidate as
- ). Such a high-level semantic unit allows the
- ). These tasks require deductive, mathematical, commonsense, lexical reasoning a
- shows, depending on different problems, a thought could be a couple of words (Cr
- Task overview. Input, output, thought examples are in blue.
- Game of 24 Results.

## Key Tables

- [Pending table extraction]

---
*Overview generated: 2026-05-31T14:04:32.432818+00:00*
