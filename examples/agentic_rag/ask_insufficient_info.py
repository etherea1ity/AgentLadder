from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("zzzzqwerty asdfgh nohit")
print(result.state.evidence_pack.evidence_status)
print(result.answer_frame.final_text)
