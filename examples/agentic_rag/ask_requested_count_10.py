from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("给我 10 篇 Agentic RAG 相关论文，并按路线分类")
print(result.answer_frame.final_text)
print("candidate_source_budget=", result.state.search_plan.candidate_source_budget)
