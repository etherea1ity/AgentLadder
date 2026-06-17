from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("Explain Agentic RAG evidence verification")
print(result.answer_frame.final_text)
