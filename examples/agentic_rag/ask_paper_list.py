from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("List Agentic RAG papers by route")
print(result.answer_frame.final_text)
