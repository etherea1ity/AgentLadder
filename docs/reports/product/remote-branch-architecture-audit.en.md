# Remote Branch Architecture and Execution Audit

Language: [Chinese](./remote-branch-architecture-audit.md) | English

Audited 34 remote branches (32 unique commits). Every unique commit ran `compileall` and its full `pytest` suite in an isolated detached worktree.

- Compile passed: 34/34
- Historical branch tests passed: 33/34
- All current static architecture gates present: 0/34

`origin/rag` is the only failing branch. It is an independent legacy line whose failures cover the real Agentic RAG API/runtime, visual assets, SSE lifecycle, and corpus validation. The other branches are incremental chapter snapshots; passing their own tests does not make them final-product complete. Live DeepSeek replay belongs only to the repaired latest reliable branch and must not be conflated with historical unit-test evidence.

| Branch | Commit | Compile | Tests | Current hard gates |
| --- | --- | ---: | ---: | ---: |
| `origin/chapter-1-minimal-loop` | `799c5dc591fc` | PASS | PASS | INCOMPLETE |
| `origin/chapter-2-tool-calling` | `bd3c13d805e9` | PASS | PASS | INCOMPLETE |
| `origin/chapter-3-hooks-and-trace` | `c12530f033d2` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-eval-contract` | `7c075ad79ad2` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-product-baseline` | `3266fea1f7cd` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-product-benchmarks` | `1642ae6f7313` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-product-external-benchmarks` | `78e157071c61` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-product-live-backtest` | `d9f6b11c2630` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-product-polish` | `cd2048438b25` | PASS | PASS | INCOMPLETE |
| `origin/codex/agent-runtime-integration` | `ac6f83eb0cb4` | PASS | PASS | INCOMPLETE |
| `origin/codex/algorithm-suite-freeze` | `b440df32c71d` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch03-algorithm-roadmap` | `65ca523c99c8` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch04-harness-config` | `02afaeaf63ed` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch05-todo-planning` | `8efe6489425c` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch06-07-context` | `bf972514b9d9` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch08-provider-recovery` | `8a47ccf745e6` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch09-skills-runtime` | `c3fadfa0608f` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch10-memory` | `3c43fa695c2d` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch12-13-evidence-runtime` | `49baa785ed7b` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch14-durable-tasks` | `36e192ef9fdb` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch15-background-scheduler` | `ac0e79de8997` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch16-subagents-team-worktree` | `40389110a1d4` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch17-mcp` | `e0890d143199` | PASS | PASS | INCOMPLETE |
| `origin/codex/ch18-production-runtime` | `270e9ca2343f` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-a-evidence-eval` | `445fad2ba6b3` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-b-tiny-pretrain` | `cf16dbbf2936` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-c-trajectory-distillation` | `dd1c52f6c847` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-d-tiny-moe` | `e2084efe8eb3` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-e-fp16-fp4` | `573aecf5d5fb` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-e-tiny-sparse-moe` | `e2084efe8eb3` | PASS | PASS | INCOMPLETE |
| `origin/codex/lab-h-fp16-fp4` | `573aecf5d5fb` | PASS | PASS | INCOMPLETE |
| `origin/codex/permission-engine` | `d96234538dd7` | PASS | PASS | INCOMPLETE |
| `origin/main` | `aa19ae8d3141` | PASS | PASS | INCOMPLETE |
| `origin/rag` | `ecd70e715d68` | PASS | FAIL | INCOMPLETE |

## References

- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)
- [AutoGen state](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/state.html)
- [Mem0](https://github.com/mem0ai/mem0)
- [OpenHands architecture](https://github.com/OpenHands/OpenHands/blob/main/docs/architecture.md)

Note: this report contains no credentials, environment values, or full command output.
