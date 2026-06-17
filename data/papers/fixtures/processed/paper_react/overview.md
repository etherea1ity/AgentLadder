# ReAct: Synergizing Reasoning and Acting in Language Models

YEAR: 2022
VENUE: ICLR 2023
URL: https://arxiv.org/abs/2210.03629
PDF_URL: https://arxiv.org/pdf/2210.03629.pdf
ARXIV_ID: 2210.03629
DOMAIN: agent-basic-paradigms, reasoning, tool-use
METHOD_TAGS: ReAct, few-shot-prompting, interleaved-reasoning-acting, tool-augmented-LLM
BENCHMARKS: HotpotQA, FEVER, ALFWorld, WebShop, ALFWorld

## One Sentence Summary

While large language models (LLMs) have demonstrated impressive performance across tasks in language understanding and interactive decision making, their abilities for reasoning (e.g. chain-of-thought prompting) and acting (e.g. action plan generation) have primarily been studied as separate topics.

## Why It Matters



## Core Idea

[Auto-generated overview — to be refined with LLM]

## Method

Key methodological approach from 301 text chunks across the paper.

## Experiments

Benchmarks evaluated: HotpotQA, FEVER, ALFWorld, WebShop, ALFWorld

## Limitations

[To be populated from paper analysis]

## Useful For These Questions

- What is the core contribution of ReAct?
- How does this paper relate to Agent Ladder?
- What are the key methodological innovations?

## Key Figures

- (1) Comparison of 4 prompting methods, (a) Standard, (b) Chain-of-thought (CoT,
- (1b)). On the other hand,
- ). ReAct
- (1c) is unable to generate the correct ﬁnal
- (2a) fails to comprehend from the
- ,
- (1d), (2b)). Each in-context example is a human trajectory of actions, thoughts,
- (1)), we alternate the generation of thoughts and actions so that the
- (2)), thoughts only need to
- in Section 4.
- PaLM-540B prompting results on
- shows HotpotQA and Fever results using PaLM-
- Types of success and failure modes of ReAct and CoT on HotpotQA, as well as thei
- . Some key observations are as follows:
- , the best prompting

## Key Tables

- [Pending table extraction]

---
*Overview generated: 2026-05-31T13:43:28.380987+00:00*
