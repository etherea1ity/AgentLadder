from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("Compare Agentic RAG and world model agent routes")
print(result.answer_frame.final_text)
