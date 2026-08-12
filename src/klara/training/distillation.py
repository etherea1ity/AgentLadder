"""Public-trajectory validation, hard-label SFT, and held-out evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import torch
from torch.nn import functional as F

from klara.eval.trajectory import canonical_json, leakage_findings, stable_sha256
from klara.training.data import CausalBatch, IGNORE_INDEX
from klara.training.model import TinyDecoderLM
from klara.training.tokenizer import ByteTokenizer
from klara.training.trainer import model_state_sha256, resolve_device, seed_everything


DISTILLATION_SCHEMA_VERSION = "klara.public-teacher-manifest.v1"
DISTILLATION_SCORER_VERSION = "klara.public-trajectory-sft.v1"
ALLOWED_TEACHERS = frozenset({"qwen", "deepseek"})
ALLOWED_SPLITS = frozenset({"train", "validation", "test"})
ACTION_CANDIDATES = ("web_search", "web_fetch", "answer", "abstain")
EXAMPLE_FIELDS = frozenset(
    {
        "example_id",
        "teacher",
        "split",
        "state",
        "observation",
        "policy_decision",
        "outcome",
        "action",
    }
)


@dataclass(frozen=True)
class PublicTeacherExample:
    """One bounded public state-to-action label from an API-teacher export."""

    example_id: str
    teacher: str
    split: str
    state: str
    observation: str
    policy_decision: str
    outcome: str
    action: str

    def __post_init__(self) -> None:
        """Reject private fields, unsupported labels, and malformed examples."""

        if not self.example_id or self.teacher not in ALLOWED_TEACHERS:
            raise ValueError("example requires an ID and an approved teacher")
        if self.split not in ALLOWED_SPLITS:
            raise ValueError(f"unsupported distillation split: {self.split}")
        if self.action not in ACTION_CANDIDATES:
            raise ValueError(f"unsupported public action: {self.action}")
        if self.policy_decision not in {"allow", "block"}:
            raise ValueError("policy_decision must be allow or block")
        if not all((self.state, self.observation, self.outcome)):
            raise ValueError("public trajectory fields must not be empty")
        private_markers = (
            "chain_of_thought",
            "chain of thought",
            "hidden_reasoning",
            "hidden reasoning",
            "reasoning_content",
            "raw_prompt",
            "raw prompt",
            "tool_arguments",
            "tool arguments",
            "raw_tool_result",
            "raw tool result",
        )
        public_text = canonical_json(self.to_dict()).lower()
        if leakage_findings(self.to_dict()) or any(
            marker in public_text for marker in private_markers
        ):
            raise ValueError("distillation example contains private or secret data")

    def to_dict(self) -> dict[str, str]:
        """Return the exact public example contract."""

        return {
            "example_id": self.example_id,
            "teacher": self.teacher,
            "split": self.split,
            "state": self.state,
            "observation": self.observation,
            "policy_decision": self.policy_decision,
            "outcome": self.outcome,
            "action": self.action,
        }

    @property
    def prompt(self) -> str:
        """Render only public fields into the student decision prompt."""

        return (
            f"state={self.state}|observation={self.observation}|"
            f"outcome={self.outcome}|next_action="
        )

    @property
    def content_hash(self) -> str:
        """Hash semantic content without IDs, teacher identity, or split."""

        return stable_sha256(
            canonical_json(
                {
                    "state": self.state,
                    "observation": self.observation,
                    "policy_decision": self.policy_decision,
                    "outcome": self.outcome,
                    "action": self.action,
                }
            )
        )


@dataclass(frozen=True)
class FrozenTeacherManifest:
    """Validated single manifest shared by both API teachers."""

    manifest_id: str
    collection: dict[str, Any]
    teachers: tuple[dict[str, str], ...]
    examples: tuple[PublicTeacherExample, ...]
    sha256: str

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> "FrozenTeacherManifest":
        """Load an immutable manifest and enforce its complete safety contract."""

        raw_bytes = path.read_bytes()
        actual_sha256 = stable_sha256(raw_bytes)
        if actual_sha256 != expected_sha256:
            raise ValueError("frozen teacher manifest SHA-256 mismatch")
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict) or raw.get("schema_version") != DISTILLATION_SCHEMA_VERSION:
            raise ValueError("unsupported teacher manifest schema")
        collection = raw.get("collection")
        raw_teachers = raw.get("teachers")
        raw_examples = raw.get("examples")
        if not isinstance(collection, dict) or not isinstance(raw_teachers, list):
            raise ValueError("teacher manifest metadata is malformed")
        if not isinstance(raw_examples, list) or not raw_examples:
            raise ValueError("teacher manifest requires examples")
        teachers = tuple(dict(item) for item in raw_teachers if isinstance(item, dict))
        teacher_names = {str(item.get("provider", "")) for item in teachers}
        if teacher_names != ALLOWED_TEACHERS:
            raise ValueError("one frozen manifest must contain Qwen and DeepSeek")
        for teacher in teachers:
            if teacher.get("supervision") != "hard_label_sft":
                raise ValueError("API teachers must use hard-label SFT only")
            if float(teacher.get("kl_weight", "nan")) != 0.0:
                raise ValueError("API teachers cannot supply same-vocabulary KL")
        examples: list[PublicTeacherExample] = []
        for index, item in enumerate(raw_examples):
            if not isinstance(item, dict) or set(item) != EXAMPLE_FIELDS:
                raise ValueError(f"example {index} violates the exact public schema")
            examples.append(PublicTeacherExample(**{key: str(value) for key, value in item.items()}))
        example_ids = [item.example_id for item in examples]
        content_hashes = [item.content_hash for item in examples]
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("teacher manifest contains duplicate example IDs")
        if len(content_hashes) != len(set(content_hashes)):
            raise ValueError("teacher manifest contains duplicate public trajectories")
        if {item.teacher for item in examples} != ALLOWED_TEACHERS:
            raise ValueError("both teachers must contribute public examples")
        split_hashes = {
            split: {item.content_hash for item in examples if item.split == split}
            for split in ALLOWED_SPLITS
        }
        if any(not values for values in split_hashes.values()):
            raise ValueError("train, validation, and test splits must all be non-empty")
        if (
            split_hashes["train"] & split_hashes["validation"]
            or split_hashes["train"] & split_hashes["test"]
            or split_hashes["validation"] & split_hashes["test"]
        ):
            raise ValueError("train/dev/test content hashes must be disjoint")
        return cls(
            manifest_id=str(raw.get("manifest_id", "")),
            collection=collection,
            teachers=teachers,
            examples=tuple(examples),
            sha256=actual_sha256,
        )

    def split(self, name: str) -> tuple[PublicTeacherExample, ...]:
        """Return one frozen split in manifest order."""

        return tuple(item for item in self.examples if item.split == name)

    def dataset_summary(self) -> dict[str, Any]:
        """Return measurable validation, deduplication, and split evidence."""

        split_hashes = {
            split: stable_sha256(
                canonical_json([item.content_hash for item in self.split(split)])
            )
            for split in sorted(ALLOWED_SPLITS)
        }
        return {
            "manifest_id": self.manifest_id,
            "manifest_sha256": self.sha256,
            "total_examples": len(self.examples),
            "teacher_counts": {
                teacher: sum(item.teacher == teacher for item in self.examples)
                for teacher in sorted(ALLOWED_TEACHERS)
            },
            "split_counts": {
                split: len(self.split(split)) for split in sorted(ALLOWED_SPLITS)
            },
            "split_sha256": split_hashes,
            "schema_validation_rate": 1.0,
            "redaction_pass_rate": 1.0,
            "deduplication_pass_rate": 1.0,
            "split_hashes_disjoint": True,
            "public_fields_only": True,
        }


@dataclass(frozen=True)
class DistillationResult:
    """Measured pre/post SFT decision quality and optimization telemetry."""

    pre_sft_accuracy: float
    post_sft_accuracy: float
    validation_accuracy: float
    improved: bool
    train_loss_first: float
    train_loss_final: float
    duration_seconds: float
    gradients_finite: bool
    peak_allocated_bytes: int
    model_state_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible result."""

        return self.__dict__.copy()


def build_sft_batches(
    examples: tuple[PublicTeacherExample, ...],
    tokenizer: ByteTokenizer,
    *,
    sequence_length: int,
    batch_size: int,
) -> tuple[CausalBatch, ...]:
    """Build causal rows whose loss covers only hard-label completion bytes."""

    rows: list[tuple[list[int], list[int], list[int]]] = []
    for example in examples:
        prompt_ids = tokenizer.encode(example.prompt, add_bos=True, add_eos=False)
        completion_ids = tokenizer.encode(example.action, add_bos=False, add_eos=True)
        tokens = prompt_ids + completion_ids
        if len(tokens) > sequence_length + 1:
            raise ValueError("distillation example exceeds configured sequence length")
        inputs = tokens[:-1]
        next_tokens = tokens[1:]
        prompt_prediction_count = max(0, len(prompt_ids) - 1)
        labels = [IGNORE_INDEX] * prompt_prediction_count + next_tokens[prompt_prediction_count:]
        visible = [1] * len(inputs)
        padding = sequence_length - len(inputs)
        inputs.extend([tokenizer.pad_token_id] * padding)
        labels.extend([IGNORE_INDEX] * padding)
        visible.extend([0] * padding)
        rows.append((inputs, labels, visible))
    batches: list[CausalBatch] = []
    for start in range(0, len(rows), batch_size):
        selected = rows[start : start + batch_size]
        batches.append(
            CausalBatch(
                input_ids=torch.tensor([row[0] for row in selected], dtype=torch.long),
                labels=torch.tensor([row[1] for row in selected], dtype=torch.long),
                attention_mask=torch.tensor([row[2] for row in selected], dtype=torch.bool),
            )
        )
    return tuple(batches)


def tool_decision_accuracy(
    model: TinyDecoderLM,
    examples: tuple[PublicTeacherExample, ...],
    tokenizer: ByteTokenizer,
    *,
    device: torch.device,
    precision: str = "fp32",
) -> float:
    """Choose the candidate with highest conditional hard-label likelihood."""

    model.to(device).eval()
    correct = 0
    with torch.inference_mode():
        for example in examples:
            scores = {
                action: _completion_log_likelihood(
                    model,
                    tokenizer,
                    prompt=example.prompt,
                    completion=action,
                    device=device,
                    precision=precision,
                )
                for action in ACTION_CANDIDATES
            }
            prediction = max(ACTION_CANDIDATES, key=lambda action: scores[action])
            correct += int(prediction == example.action)
    return correct / len(examples)


def train_hard_label_sft(
    model: TinyDecoderLM,
    manifest: FrozenTeacherManifest,
    tokenizer: ByteTokenizer,
    *,
    steps: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
    gradient_clip: float,
    seed: int,
    device_name: str,
) -> DistillationResult:
    """Fine-tune on public API-teacher labels without logits or hidden reasoning."""

    seed_everything(seed)
    device = resolve_device(device_name)
    train_batches = build_sft_batches(
        manifest.split("train"),
        tokenizer,
        sequence_length=model.config.max_sequence_length,
        batch_size=batch_size,
    )
    pre_sft = tool_decision_accuracy(
        model,
        manifest.split("test"),
        tokenizer,
        device=device,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    generator = torch.Generator(device="cpu").manual_seed(seed)
    order: list[int] = []
    index = 0
    losses: list[float] = []
    gradients_finite = True
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
        torch.cuda.synchronize(device)
    started = perf_counter()
    model.train()
    for _ in range(steps):
        if index >= len(order):
            order = torch.randperm(len(train_batches), generator=generator).tolist()
            index = 0
        batch = train_batches[order[index]].to(device)
        index += 1
        optimizer.zero_grad(set_to_none=True)
        output = model(
            batch.input_ids,
            attention_mask=batch.attention_mask,
            labels=batch.labels,
        )
        if output.language_model_loss is None or output.loss is None:
            raise RuntimeError("hard-label SFT did not produce cross entropy")
        loss = output.loss
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("non-finite hard-label SFT loss")
        loss.backward()
        step_finite = all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
        gradients_finite = gradients_finite and step_finite
        if not step_finite:
            raise FloatingPointError("non-finite hard-label SFT gradient")
        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
        optimizer.step()
        losses.append(float(loss.detach().item()))
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    duration = perf_counter() - started
    peak = int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
    validation = tool_decision_accuracy(
        model,
        manifest.split("validation"),
        tokenizer,
        device=device,
    )
    post_sft = tool_decision_accuracy(
        model,
        manifest.split("test"),
        tokenizer,
        device=device,
    )
    return DistillationResult(
        pre_sft_accuracy=pre_sft,
        post_sft_accuracy=post_sft,
        validation_accuracy=validation,
        improved=post_sft > pre_sft,
        train_loss_first=losses[0],
        train_loss_final=losses[-1],
        duration_seconds=duration,
        gradients_finite=gradients_finite,
        peak_allocated_bytes=peak,
        model_state_sha256=model_state_sha256(model),
    )


def _completion_log_likelihood(
    model: TinyDecoderLM,
    tokenizer: ByteTokenizer,
    *,
    prompt: str,
    completion: str,
    device: torch.device,
    precision: str = "fp32",
) -> float:
    """Score one candidate completion using only its conditional token losses."""

    prompt_ids = tokenizer.encode(prompt, add_bos=True, add_eos=False)
    completion_ids = tokenizer.encode(completion, add_bos=False, add_eos=True)
    tokens = prompt_ids + completion_ids
    input_ids = torch.tensor([tokens[:-1]], dtype=torch.long, device=device)
    if precision not in {"fp32", "fp16"}:
        raise ValueError("decision scorer precision must be fp32 or fp16")
    context = (
        torch.autocast("cuda", dtype=torch.float16)
        if precision == "fp16" and device.type == "cuda"
        else nullcontext()
    )
    with context:
        output = model(input_ids)
        log_probabilities = F.log_softmax(output.logits, dim=-1)
    start = len(prompt_ids) - 1
    positions = torch.arange(start, len(tokens) - 1, device=device)
    targets = torch.tensor(completion_ids, dtype=torch.long, device=device)
    return float(log_probabilities[0, positions, targets].mean().item())
