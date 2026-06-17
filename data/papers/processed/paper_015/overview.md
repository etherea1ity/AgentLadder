# Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks

YEAR: 2020
VENUE: NeurIPS 2020
URL: https://arxiv.org/abs/2005.11401
PDF_URL: https://arxiv.org/pdf/2005.11401.pdf
ARXIV_ID: 2005.11401
DOMAIN: agentic-rag, foundation
METHOD_TAGS: RAG, retrieval-augmented, parametric-memory, non-parametric-memory
BENCHMARKS: FEVER

## One Sentence Summary

Large pre-trained language models have been shown to store factual knowledge in their parameters, and achieve state-of-the-art results when ﬁne-tuned on down- stream NLP tasks. However, their ability to access and precisely manipulate knowl- edge is still limited, and hence on knowledge-intensive ta

## Why It Matters



## Core Idea

[Auto-generated overview — to be refined with LLM]

## Method

Key methodological approach from 183 text chunks across the paper.

## Experiments

Benchmarks evaluated: FEVER

## Limitations

[To be populated from paper analysis]

## Useful For These Questions

- What is the core contribution of Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks?
- How does this paper relate to Agent Ladder?
- What are the key methodological innovations?

## Key Figures

- Overview of our approach. We combine a pre-trained retriever (Query Encoder + Do
- , our models
- shows
- RAG-Token document posterior p(zi|x, yi, y−i) for each generated token for input
- (left) shows that retrieving more documents at test time monotonically improves
- (right) shows that retrieving more documents leads to higher Rouge-L for
- Left: NQ performance as more documents are retrieved. Center: Retrieval recall p
- shows results for RAG along with state-of-the-art models. On all four open-domai
- Open-Domain QA Test Scores. For TQA,
- Generation and classiﬁcation Test Scores.
- , RAG-Sequence outperforms BART on Open MS-MARCO NLG by 2.6 Bleu
- shows some generated answers
- shows that RAG-Token performs better than RAG-Sequence on Jeopardy question gene
- shows typical generations from each model.
- shows our results on FEVER. For 3-way classiﬁcation, RAG scores are within 4.3%

## Key Tables

- [Pending table extraction]

---
*Overview generated: 2026-05-31T14:05:19.061676+00:00*
