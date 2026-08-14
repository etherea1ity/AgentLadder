# Memory Architecture Failure Analysis

Language: [Chinese](./memory-architecture-failure-analysis.md) | English

The 100-question repair replay fixed tool protocol and retrieval: 100/100 runs completed, valid single `memory_search` usage was 100%, Recall@20 rose from 0.6521 to 0.7402, and P0 remained zero.

The final gate still fails. Agent F1 is 0.3910 versus 0.4619 for the same-model dedicated QA baseline; Exact Match is 0.11 versus 0.25. The remaining defect is no longer missing evidence. General-Agent prompting, ranked-observation organization, and answer extraction underperform the dedicated QA prompt.

Repaired structural defects include global Memory IDs overwriting other owner scopes, Memory requests entering Web Research, untrusted wrappers producing a false zero evidence score, and learned dense similarity replacing the sparse channel. Dense and sparse rankings now use RRF.

This is a repair replay on the same 100 questions, not a fresh hidden score. Agent Product Freeze and model training remain blocked.
