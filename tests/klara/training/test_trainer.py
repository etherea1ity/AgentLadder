from __future__ import annotations

import os

import torch
import pytest

from klara.training import (
    ByteTokenizer,
    ModelConfig,
    TinyDecoderLM,
    TrainConfig,
    build_causal_batches,
)
from klara.training.trainer import cpu_reproducibility_hash, train_language_model
from klara.training.cli import _validate_execution_boundary


torch.set_num_threads(1)


def _config() -> ModelConfig:
    return ModelConfig(
        hidden_size=16,
        num_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        intermediate_size=32,
        max_sequence_length=12,
    )


def test_same_seed_reproduces_exact_cpu_forward_and_generation_hash() -> None:
    tokenizer = ByteTokenizer()

    first = cpu_reproducibility_hash(
        _config(),
        tokenizer=tokenizer,
        prompt="Klara",
        seed=13,
    )
    second = cpu_reproducibility_hash(
        _config(),
        tokenizer=tokenizer,
        prompt="Klara",
        seed=13,
    )

    assert first == second


@pytest.mark.skipif(
    "SLURM_JOB_ID" not in os.environ,
    reason="bounded overfit gate runs only on HKU Slurm",
)
def test_bounded_micro_corpus_overfit_reduces_loss() -> None:
    tokenizer = ByteTokenizer()
    batches = build_causal_batches(
        ["abc abc abc abc", "abc abc abc abc"],
        tokenizer,
        sequence_length=12,
        batch_size=2,
    )
    torch.manual_seed(14)
    model = TinyDecoderLM(_config())

    result, _ = train_language_model(
        model,
        batches,
        TrainConfig(
            seed=14,
            steps=35,
            batch_size=2,
            learning_rate=0.01,
            weight_decay=0.0,
            device="cpu",
        ),
        tokenizer=tokenizer,
        generation_prompt="abc",
    )

    assert result.gradients_finite is True
    assert result.loss_reduction_fraction >= 0.30
    assert result.final_loss < result.initial_loss


def test_formal_pretrain_refuses_non_slurm_execution(monkeypatch) -> None:
    for key in (
        "SLURM_JOB_ID",
        "SLURMD_NODENAME",
        "SLURM_JOB_PARTITION",
        "AGENTLADDER_SOURCE_DIR",
        "AGENTLADDER_SOURCE_BUNDLE_SHA256",
        "AGENTLADDER_PARENT_COMMIT",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError, match="requires an HKU Slurm job"):
        _validate_execution_boundary(
            {
                "require_slurm": True,
                "remote_root": "/userhome/cs2/u3665453/AgentLadder",
            }
        )


def test_formal_pretrain_accepts_complete_hku_lineage(monkeypatch) -> None:
    deployment = "/userhome/cs2/u3665453/AgentLadder/deployments/" + "a" * 64
    environment = {
        "SLURM_JOB_ID": "123456",
        "SLURMD_NODENAME": "gpu-4080-409",
        "SLURM_JOB_PARTITION": "batch",
        "AGENTLADDER_SOURCE_DIR": deployment,
        "AGENTLADDER_SOURCE_BUNDLE_SHA256": "a" * 64,
        "AGENTLADDER_PARENT_COMMIT": "b" * 40,
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    _validate_execution_boundary(
        {
            "require_slurm": True,
            "remote_root": "/userhome/cs2/u3665453/AgentLadder",
        }
    )
