from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

result = AgenticRAGRuntime(trace_path="data/traces/examples-agentic-rag.jsonl").run("Explain figure aware RAG in Chinese, include figure")
print(result.answer_frame.final_text)
for asset in result.answer_frame.rendered_assets:
    print(asset)
