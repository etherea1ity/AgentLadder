from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("zzzzqwerty asdfgh")
print([attempt.stage for attempt in result.state.retrieval_attempts])
print(result.answer_frame.final_text)
