# 远程分支架构与执行审计

语言：中文 | [English](./remote-branch-architecture-audit.en.md)

审计了 34 个远程分支（32 个唯一提交）。每个唯一提交均在隔离 detached worktree 中执行 `compileall` 和完整 `pytest`。

- 编译通过：34/34
- 原分支测试通过：33/34
- 同时满足当前静态架构硬门：0/34

`origin/rag` 是唯一测试失败分支；它是独立旧路线，失败集中在真实 Agentic RAG API、运行时、可视资产、SSE 生命周期和语料校验。其余分支是逐章演进快照，测试通过不等于最终产品架构完整。正式 DeepSeek 回放只对修复后的最新可靠分支执行，不能把历史单测当成真实模型成绩。

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

## 架构参照

- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)
- [AutoGen state](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/state.html)
- [Mem0](https://github.com/mem0ai/mem0)
- [OpenHands architecture](https://github.com/OpenHands/OpenHands/blob/main/docs/architecture.md)

注：本报告不包含凭据、环境变量值或完整命令输出。
