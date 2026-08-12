# Final Branch And Ancestry Report

The implementation preserves the historical course checkpoints and uses a
strict stacked chain. No force-push, hard reset, or wholesale legacy-tree merge
was used.

| Order | Branch | Verified head | Role |
| ---: | --- | --- | --- |
| 0 | `codex/ch03-algorithm-roadmap` | `65ca523c99c8fe03c6ef438a7e914c836a32709a` | roadmap and gate contract |
| 1 | `codex/lab-a-evidence-eval` | `445fad2ba6b3284478276ee0f4e815946218221e` | evidence and trajectory eval |
| 2 | `codex/lab-b-tiny-pretrain` | `cf16dbbf29366669019a0528935f6fba268e3bab` | custom dense model and HKU training |
| 3 | `codex/lab-c-trajectory-distillation` | `dd1c52f6c847fe136f6f877ca803fcc7fff6d216` | public-trajectory distillation |
| 4 | `codex/lab-d-tiny-moe` | `e2084efe8eb32a13bb95305b97d894aadb4166ff` | implementation branch for four-expert top-2 MoE |
| 4a | `codex/lab-e-tiny-sparse-moe` | `e2084efe8eb32a13bb95305b97d894aadb4166ff` | canonical roadmap alias; no history rewrite |
| 5 | `codex/lab-e-fp16-fp4` | `573aecf5d5fbb0008af2f99eb4d82b4dd9cabb20` | implementation branch for CUDA FP16 and FP4/W4A16 |
| 5a | `codex/lab-h-fp16-fp4` | `573aecf5d5fbb0008af2f99eb4d82b4dd9cabb20` | canonical roadmap alias; no history rewrite |
| 6 | `codex/algorithm-suite-freeze` | final freeze branch | end-to-end gate and docs |

`git merge-base --is-ancestor` returned success for every adjacent pair before
the freeze work began.

The Lab E/H canonical aliases were added after the corresponding implementation
branches had passed and been pushed. Each alias points to the identical verified
commit; no commit was rebased, copied, or force-pushed.

Historical refs preserved read-only:

```text
origin/chapter-1-minimal-loop
origin/chapter-2-tool-calling
origin/chapter-3-hooks-and-trace
origin/main
origin/rag
v0.3-agentic-rag
```

Legacy RAG ideas around sources, citations, evidence packs, and decision records
were ported deliberately. The old `src/agent_ladder` package was not merged into
the current `src/klara` course line.
