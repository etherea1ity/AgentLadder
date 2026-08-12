from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import torch

from klara.training.config import ModelConfig
from klara.training.data import IGNORE_INDEX
from klara.training.distillation import (
    FrozenTeacherManifest,
    PublicTeacherExample,
    build_sft_batches,
    tool_decision_accuracy,
)
from klara.training.model import TinyDecoderLM
from klara.training.tokenizer import ByteTokenizer


FIXTURE = Path("tests/fixtures/algorithm/lab_c_public_teacher_manifest.json")


def _fixture_hash() -> str:
    return hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def _model_config() -> ModelConfig:
    return ModelConfig(
        hidden_size=16,
        num_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        intermediate_size=32,
        max_sequence_length=128,
    )


def test_frozen_manifest_has_both_teachers_and_disjoint_splits() -> None:
    manifest = FrozenTeacherManifest.load(FIXTURE, expected_sha256=_fixture_hash())

    summary = manifest.dataset_summary()
    assert summary["total_examples"] == 28
    assert summary["teacher_counts"] == {"deepseek": 14, "qwen": 14}
    assert summary["split_counts"] == {"test": 8, "train": 16, "validation": 4}
    assert summary["split_hashes_disjoint"] is True
    assert summary["redaction_pass_rate"] == 1.0


def test_manifest_hash_is_immutable() -> None:
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        FrozenTeacherManifest.load(FIXTURE, expected_sha256="0" * 64)


def test_public_example_rejects_hidden_reasoning_and_secret_values() -> None:
    with pytest.raises(ValueError, match="private or secret"):
        PublicTeacherExample(
            example_id="bad",
            teacher="qwen",
            split="train",
            state="reasoning",
            observation="chain_of_thought must never be retained",
            policy_decision="allow",
            outcome="needs_evidence",
            action="web_search",
        )


def test_manifest_rejects_unknown_fields_and_cross_split_duplicates(tmp_path: Path) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["examples"][0]["raw_prompt"] = "not allowed"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="exact public schema"):
        FrozenTeacherManifest.load(invalid, expected_sha256=hashlib.sha256(invalid.read_bytes()).hexdigest())

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["examples"][-1].update(
        {
            key: value
            for key, value in raw["examples"][0].items()
            if key not in {"example_id", "teacher", "split"}
        }
    )
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate public trajectories"):
        FrozenTeacherManifest.load(
            duplicate,
            expected_sha256=hashlib.sha256(duplicate.read_bytes()).hexdigest(),
        )


def test_sft_labels_cover_only_completion_tokens() -> None:
    tokenizer = ByteTokenizer()
    manifest = FrozenTeacherManifest.load(FIXTURE, expected_sha256=_fixture_hash())
    example = manifest.split("train")[0]
    batch = build_sft_batches(
        (example,), tokenizer, sequence_length=128, batch_size=1
    )[0]
    prompt_length = len(tokenizer.encode(example.prompt, add_bos=True, add_eos=False))
    completion_length = len(tokenizer.encode(example.action, add_bos=False, add_eos=True))

    assert torch.all(batch.labels[0, : prompt_length - 1].eq(IGNORE_INDEX))
    assert int(batch.labels[0].ne(IGNORE_INDEX).sum().item()) == completion_length
    assert batch.input_ids.shape == (1, 128)


def test_tool_decision_scorer_is_bounded_and_deterministic() -> None:
    tokenizer = ByteTokenizer()
    manifest = FrozenTeacherManifest.load(FIXTURE, expected_sha256=_fixture_hash())
    torch.manual_seed(123)
    model = TinyDecoderLM(_model_config())

    first = tool_decision_accuracy(
        model, manifest.split("validation"), tokenizer, device=torch.device("cpu")
    )
    second = tool_decision_accuracy(
        model, manifest.split("validation"), tokenizer, device=torch.device("cpu")
    )

    assert 0.0 <= first <= 1.0
    assert first == second
