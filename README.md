# Klara / AgentLadder

语言：中文 | [English](./README.en.md)

一个从零构建的开源全栈 Agent Harness，并用统一事件流与轨迹评测，从轨迹蒸馏一路做到自训练 Sparse MoE 小模型的完整项目。

## 这是什么

Klara 不是一个单一 Demo，而是一条**循序渐进的课程线**：每个章节留下一个可运行、可测试、可解释的 Klara 版本。

- **Foundation Track（Chapter 1~18）**：从一个最小 LLM Loop 逐步构建工具调用、Hooks/Trace、Harness、Todo、上下文、记忆、RAG、任务系统、Subagent/Team、MCP，直到生产级运行时与评测桥。
- **Advanced Labs**：证据评测、轨迹蒸馏、Tiny Pretrain、Sparse MoE、FP16/FP4。
- **Klara MoE**：自训练 4-Expert Top-2 Sparse MoE，并对比 Qwen QLoRA 与 DeepSeek 基线。

## 章节导航

| 章节 | 主题 | 文档 |
| --- | --- | --- |
| 1 | 最小 LLM Loop | [ch01-minimal-agent-loop](./docs/chapters/ch01-minimal-agent-loop.md) |
| 2 | 工具调用 | [ch02-tool-calling](./docs/chapters/ch02-tool-calling.md) |
| 3 | Hooks 与 Trace | [ch03-hooks-and-trace](./docs/chapters/ch03-hooks-and-trace.md) |
| 4 | Harness 与配置 | [ch04-harness-and-config](./docs/chapters/ch04-harness-and-config.md) |
| 5 | Todo 规划 | [ch05-todo-planning](./docs/chapters/ch05-todo-planning.md) |
| 6 | 系统提示与上下文组装 | [ch06-system-prompt-and-context-assembly](./docs/chapters/ch06-system-prompt-and-context-assembly.md) |
| 7 | 上下文压缩 | [ch07-context-compression](./docs/chapters/ch07-context-compression.md) |
| 8 | 错误恢复与回退 | [ch08-error-recovery-and-fallback](./docs/chapters/ch08-error-recovery-and-fallback.md) |
| 9 | Skills 程序化记忆 | [ch09-skills-procedural-memory](./docs/chapters/ch09-skills-procedural-memory.md) |
| 10 | 记忆系统 | [ch10-memory-system](./docs/chapters/ch10-memory-system.md) |
| 12 | 受控 Agentic RAG | [ch12-controlled-agentic-rag](./docs/chapters/ch12-controlled-agentic-rag.md) |
| 13 | 研究 Agent | [ch13-research-agent](./docs/chapters/ch13-research-agent.md) |
| 14 | 持久任务 | [ch14-durable-tasks](./docs/chapters/ch14-durable-tasks.md) |
| 15 | 后台调度 | [ch15-background-scheduler](./docs/chapters/ch15-background-scheduler.md) |
| 16 | Subagent 与 Team | [ch16-subagents-teams-worktrees](./docs/chapters/ch16-subagents-teams-worktrees.md) |
| 17 | MCP 与外部工具 | [ch17-mcp-and-external-tools](./docs/chapters/ch17-mcp-and-external-tools.md) |
| 18 | 生产运行时与评测桥 | [ch18-production-runtime-and-eval-bridge](./docs/chapters/ch18-production-runtime-and-eval-bridge.md) |
| 附 | 权限引擎 | [permission-engine](./docs/chapters/permission-engine.md) |

## Advanced Labs

- [算法套件：证据、蒸馏、MoE 与 FP16/FP4](./docs/labs/algorithm-suite.md)
- [Agent 产品冻结就绪度](./docs/labs/agent-product-freeze-readiness.md)
- [Prompt 上下文恢复加固](./docs/labs/prompt-context-recovery-hardening.md)

## 快速开始

准备 `.env` 后启动前后端：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

## 总路线

完整课程规划见 [Klara Roadmap](./docs/skills/roadmap.md)。

## 分支

项目按章节循序渐进拆分分支：

```text
main
 -> chapter-2-tool-calling
 -> codex/ch03-algorithm-roadmap
 -> codex/ch04-harness-config
 -> ...
 -> codex/ch18-production-runtime
 -> codex/agent-product-*
 -> codex/klara-*
```
