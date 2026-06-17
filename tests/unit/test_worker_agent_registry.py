from agent_ladder.rag.agentic.registry import WorkerAgentRegistry
from agent_ladder.rag.contracts.agentic import WorkerAgentSpec


def test_worker_agent_registry_registers_one_shot_worker():
    reg = WorkerAgentRegistry()
    spec = WorkerAgentSpec(worker_id="answer_writer", name="Answer Writer", input_schema="EvidencePack", output_schema="AnswerFrameV2")
    reg.register_spec(spec)
    assert reg.get("answer_writer").max_calls_per_run == 1
