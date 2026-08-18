"""GRPO training for the Klara four-expert top-2 sparse MoE model.

GRPO rollouts are generated with the current policy (frozen in eval mode) and
scored with a task-level reward:

    reward = task_success + tool_selection_correct + valid_arguments
             - invalid_calls - over_steps

A policy-version step then recomputes token log-probabilities under the same
policy and performs one normalized-advantage batch update.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR

from klara.eval.teacher_rollout import TOOL_NAMES, TOOL_SCHEMAS
from klara.training.checkpoint import file_sha256
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig
from klara.training.model import TinyDecoderLM
from klara.training.sft import (
    _amp_context,
    count_parameters,
    load_pretrain_model_weights,
)
from klara.training.trainer import model_state_sha256, resolve_device, seed_everything

GRPO_CHECKPOINT_FORMAT = "klara.moe-grpo.checkpoint.v1"
GRPO_LOG_SCHEMA = "klara.moe-grpo.log.v1"

GRPO_SYSTEM_PROMPT = """You are Klara under GRPO training. Use only the tools listed in the task.
You may emit zero or more tool calls. Put every tool call on its own line exactly as:
<tool_call>{"name":"...","arguments":{...}}</tool_call>
When you have the final answer, emit exactly:
<final_answer>your concise answer</final_answer>
Never invent tool results."""


@dataclass(frozen=True)
class GRPOConfig:
    """Optimization and reward contract for GRPO training."""

    seed: int = 20260816
    steps: int = 500
    group_size: int = 8
    prompts_per_step: int = 4
    max_new_tokens: int = 256
    learning_rate: float = 5e-6
    weight_decay: float = 0.01
    gradient_clip: float = 1.0
    precision: str = "bf16"
    device: str = "auto"
    warmup_steps: int = 20
    cosine_min_lr: float = 0.0
    log_every: int = 10
    checkpoint_every: int = 50
    auxiliary_loss_weight: float = 0.01
    eval_prompts: int = 32
    temperature: float = 1.0
    task_success_weight: float = 1.0
    tool_selection_weight: float = 1.0
    valid_args_weight: float = 1.0
    invalid_call_penalty: float = 1.0
    overstep_penalty: float = 1.0

    def __post_init__(self) -> None:
        if self.steps < 1:
            raise ValueError("steps must be positive")
        if self.group_size < 1 or self.prompts_per_step < 1:
            raise ValueError("group_size and prompts_per_step must be positive")
        if self.max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        if self.learning_rate <= 0 or self.gradient_clip <= 0:
            raise ValueError("learning_rate and gradient_clip must be positive")
        if self.cosine_min_lr < 0 or self.cosine_min_lr > self.learning_rate:
            raise ValueError("cosine_min_lr must be in [0, learning_rate]")
        if self.precision not in {"fp32", "fp16", "bf16"}:
            raise ValueError("precision must be fp32, fp16, or bf16")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu, or cuda")
        if self.temperature <= 0:
            raise ValueError("temperature must be positive")
        for weight in (
            self.task_success_weight,
            self.tool_selection_weight,
            self.valid_args_weight,
            self.invalid_call_penalty,
            self.overstep_penalty,
            self.auxiliary_loss_weight,
        ):
            if weight < 0:
                raise ValueError("reward and auxiliary weights must be non-negative")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GRPOConfig":
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "steps": self.steps,
            "group_size": self.group_size,
            "prompts_per_step": self.prompts_per_step,
            "max_new_tokens": self.max_new_tokens,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "gradient_clip": self.gradient_clip,
            "precision": self.precision,
            "device": self.device,
            "warmup_steps": self.warmup_steps,
            "cosine_min_lr": self.cosine_min_lr,
            "log_every": self.log_every,
            "checkpoint_every": self.checkpoint_every,
            "auxiliary_loss_weight": self.auxiliary_loss_weight,
            "eval_prompts": self.eval_prompts,
            "temperature": self.temperature,
            "task_success_weight": self.task_success_weight,
            "tool_selection_weight": self.tool_selection_weight,
            "valid_args_weight": self.valid_args_weight,
            "invalid_call_penalty": self.invalid_call_penalty,
            "overstep_penalty": self.overstep_penalty,
        }


@dataclass(frozen=True)
class ExpectedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class GRPOTask:
    """One RL task extracted from a teacher trajectory."""

    task_id: str
    instruction: str
    available_tools: tuple[str, ...]
    required_tools: tuple[str, ...]
    expected_tool_calls: tuple[ExpectedToolCall, ...]
    reference_answer: str
    acceptable_answers: tuple[str, ...]
    max_steps: int


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]
    valid: bool


@dataclass
class Rollout:
    task: GRPOTask
    prompt_len: int
    generated_ids: torch.Tensor
    decoded_text: str
    calls: tuple[ParsedToolCall, ...]
    final_answer: str
    reward: float
    invalid_calls: int
    over_steps: int
    advantage: float = 0.0


@dataclass(frozen=True)
class GRPOResult:
    initial_mean_reward: float
    final_mean_reward: float
    reward_change: float
    final_policy_loss: float
    gradients_finite: bool
    parameter_count: int
    final_step: int
    device: str
    precision: str
    logs: tuple[dict[str, Any], ...]
    model_state_sha256: str
    final_checkpoint_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_mean_reward": self.initial_mean_reward,
            "final_mean_reward": self.final_mean_reward,
            "reward_change": self.reward_change,
            "final_policy_loss": self.final_policy_loss,
            "gradients_finite": self.gradients_finite,
            "parameter_count": self.parameter_count,
            "final_step": self.final_step,
            "device": self.device,
            "precision": self.precision,
            "logs": list(self.logs),
            "model_state_sha256": self.model_state_sha256,
            "final_checkpoint_sha256": self.final_checkpoint_sha256,
        }


def _json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_tasks(path: str | Path, *, limit: int | None = None) -> list[GRPOTask]:
    """Load clean.jsonl trajectories and extract GRPO task contracts."""
    path = Path(path)
    tasks: list[GRPOTask] = []
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            task = record.get("task") or {}
            top_tool_calls = record.get("tool_calls") or []
            expected = tuple(
                ExpectedToolCall(
                    name=str(item.get("name", "")),
                    arguments=dict(item.get("arguments") or {}),
                )
                for item in top_tool_calls
                if isinstance(item, dict)
            )
            expected_behavior = task.get("expected_behavior") or {}
            required_tools = tuple(
                str(item) for item in expected_behavior.get("required_tools", [])
            )
            available_tools = tuple(
                str(item) for item in task.get("available_tools", [])
            )
            reference_answer = str(record.get("final_answer") or "")
            acceptable_answers = tuple(
                str(item) for item in task.get("acceptable_answers", [])
            )
            max_steps = int(
                expected_behavior.get("max_tool_calls", record.get("max_steps", 8))
            )
            tasks.append(
                GRPOTask(
                    task_id=str(record.get("task_id") or task.get("task_id") or len(tasks)),
                    instruction=str(task.get("instruction") or ""),
                    available_tools=available_tools,
                    required_tools=required_tools,
                    expected_tool_calls=expected,
                    reference_answer=reference_answer,
                    acceptable_answers=acceptable_answers,
                    max_steps=max_steps,
                )
            )
            if limit is not None and len(tasks) >= limit:
                break
    if not tasks:
        raise ValueError(f"no GRPO tasks found in {path}")
    return tasks


def build_rollout_prompt_text(task: GRPOTask) -> str:
    """Render a GRPO rollout prompt for one task."""
    tools_text = ", ".join(task.available_tools) if task.available_tools else "none"
    return (
        f"{GRPO_SYSTEM_PROMPT}\n\n"
        f"Task: {task.instruction}\n"
        f"Available tools: {tools_text}.\n"
    )


def _truncate_prompt_ids(prompt_ids: torch.Tensor, max_sequence_length: int) -> torch.Tensor:
    """Keep the prompt short enough for at least one generated token."""
    if prompt_ids.shape[1] <= max_sequence_length - 1:
        return prompt_ids
    return prompt_ids[:, -(max_sequence_length - 1) :]


@torch.inference_mode()
def sample_sequence(
    model: TinyDecoderLM,
    prompt_ids: torch.Tensor,
    *,
    max_new_tokens: int,
    temperature: float,
    eos_token_id: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Sample one rollout from the frozen policy and return token log-probs."""
    device = next(model.parameters()).device
    generated = prompt_ids.to(device)
    sampled_logprobs: list[torch.Tensor] = []
    for _ in range(max_new_tokens):
        if generated.shape[1] >= model.config.max_sequence_length:
            break
        context = generated[:, -model.config.max_sequence_length :]
        output = model(context)
        logits = output.logits[:, -1, :].float() / temperature
        distribution = torch.distributions.Categorical(logits=logits)
        token = distribution.sample()
        generated = torch.cat((generated, token.unsqueeze(1)), dim=1)
        sampled_logprobs.append(distribution.log_prob(token).unsqueeze(1))
        if eos_token_id is not None and bool(token.item() == eos_token_id):
            break
    if sampled_logprobs:
        return generated, torch.cat(sampled_logprobs, dim=1)
    return generated, torch.empty((generated.shape[0], 0), device=device)


def _parse_tool_calls(text: str) -> tuple[list[dict[str, Any]], str]:
    """Extract <tool_call> JSON objects and the final answer from rollout text."""
    calls: list[dict[str, Any]] = []
    for raw in re.findall(r"<tool_call>(.*?)</tool_call>", text, flags=re.S):
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            calls.append(parsed)
    match = re.search(r"<final_answer>(.*?)</final_answer>", text, flags=re.S)
    if match:
        final_answer = match.group(1).strip()
    else:
        tail = re.split(r"</tool_call>", text, maxsplit=1)
        final_answer = tail[-1].strip() if tail else ""
    return calls, final_answer


def _json_value_matches(value: Any, schema: dict[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if "enum" in schema:
        return value in schema["enum"]
    return True


def _arguments_valid(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    if not isinstance(schema, dict):
        return True
    properties = schema.get("properties")
    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if key not in arguments:
                return False
    if isinstance(properties, dict):
        for key, value in arguments.items():
            expected = properties.get(key)
            if expected is None:
                if schema.get("additionalProperties") is False:
                    return False
                continue
            if not _json_value_matches(value, expected):
                return False
    return True


def _call_is_valid(name: str, arguments: dict[str, Any]) -> bool:
    if name not in TOOL_NAMES:
        return False
    return _arguments_valid(arguments, TOOL_SCHEMAS[name])


def _normalize_answer(value: str) -> str:
    text = value.casefold().strip()
    text = "".join(text.split())
    return text.replace("“", '"').replace("”", '"')


def _answer_matches(task: GRPOTask, final_answer: str) -> bool:
    expected = list(task.acceptable_answers)
    if task.reference_answer:
        expected.insert(0, task.reference_answer)
    if not expected:
        return bool(final_answer)
    normalized = _normalize_answer(final_answer)
    if not normalized:
        return False
    return any(_normalize_answer(item) in normalized for item in expected if item)


def _tool_selection_correct(task: GRPOTask, calls: tuple[ParsedToolCall, ...]) -> bool:
    expected = [item.name for item in task.expected_tool_calls]
    observed = [call.name for call in calls]
    if not expected and not observed:
        return True
    if not expected or not observed:
        return False
    return Counter(expected) == Counter(observed)


def compute_reward(task: GRPOTask, calls: tuple[ParsedToolCall, ...], final_answer: str, config: GRPOConfig) -> float:
    """Return the scalar reward used by GRPO."""
    invalid_calls = sum(0 if call.valid else 1 for call in calls)
    over_steps = max(0, len(calls) - task.max_steps)
    task_success = 1.0 if _answer_matches(task, final_answer) else 0.0
    tool_selection = 1.0 if _tool_selection_correct(task, calls) else 0.0
    valid_args = 1.0 if calls and invalid_calls == 0 else 0.0
    reward = (
        config.task_success_weight * task_success
        + config.tool_selection_weight * tool_selection
        + config.valid_args_weight * valid_args
        - config.invalid_call_penalty * invalid_calls
        - config.overstep_penalty * over_steps
    )
    return reward


def _sequence_logprobs(
    model: TinyDecoderLM,
    *,
    generated_ids: torch.Tensor,
    prompt_len: int,
) -> torch.Tensor:
    """Return differentiable per-token log-probabilities for the rollout suffix."""
    if generated_ids.shape[1] <= prompt_len:
        return generated_ids.new_zeros((generated_ids.shape[0],))
    inputs = generated_ids[:, :-1]
    targets = generated_ids[:, 1:]
    output = model(inputs)
    log_probs = F.log_softmax(output.logits, dim=-1).gather(
        -1, targets.unsqueeze(-1)
    ).squeeze(-1)
    new_len = generated_ids.shape[1] - prompt_len
    return log_probs[:, prompt_len - 1 : prompt_len - 1 + new_len]


def _assign_advantages(rollouts: list[Rollout], group_size: int) -> None:
    """Normalize rewards within each prompt group, or globally when group_size==1."""
    if group_size > 1:
        for start in range(0, len(rollouts), group_size):
            group = rollouts[start : start + group_size]
            rewards = [rollout.reward for rollout in group]
            mean = sum(rewards) / len(rewards)
            std = (sum((r - mean) ** 2 for r in rewards) / len(rewards)) ** 0.5
            for rollout in group:
                rollout.advantage = (rollout.reward - mean) / (std + 1e-8) if std > 1e-8 else rollout.reward - mean
        return
    rewards = [rollout.reward for rollout in rollouts]
    if not rewards:
        return
    mean = sum(rewards) / len(rewards)
    std = (sum((r - mean) ** 2 for r in rewards) / len(rewards)) ** 0.5
    for rollout in rollouts:
        rollout.advantage = (rollout.reward - mean) / (std + 1e-8) if std > 1e-8 else rollout.reward - mean


def _build_optimizer(model: TinyDecoderLM, config: GRPOConfig) -> AdamW:
    return AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
        betas=(0.9, 0.95),
        eps=1e-8,
    )


def _build_scheduler(optimizer: AdamW, config: GRPOConfig) -> LambdaLR:
    total_steps = max(1, config.steps)
    warmup_steps = max(0, config.warmup_steps)
    min_lr_ratio = config.cosine_min_lr / config.learning_rate

    def lr_lambda(step: int) -> float:
        if step < warmup_steps:
            return float(step) / float(max(1, warmup_steps))
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
        return min_lr_ratio + (1.0 - min_lr_ratio) * cosine

    return LambdaLR(optimizer, lr_lambda)


def save_grpo_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None,
    step: int,
    metadata: dict[str, Any],
) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "format": GRPO_CHECKPOINT_FORMAT,
        "model_config": model.config.to_dict(),
        "model_state": {
            key: value.detach().cpu() for key, value in model.state_dict().items()
        },
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "scaler_state": scaler.state_dict() if scaler is not None else None,
        "step": step,
        "metadata": metadata,
    }
    torch.save(payload, temporary)
    temporary.replace(path)
    return file_sha256(path)


def load_grpo_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    actual_hash = file_sha256(path)
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ValueError("checkpoint SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or payload.get("format") != GRPO_CHECKPOINT_FORMAT:
        raise ValueError("unsupported GRPO checkpoint format")
    saved_config = ModelConfig.from_dict(dict(payload.get("model_config", {})))
    if saved_config != model.config:
        raise ValueError("checkpoint model config does not match target model")
    model.load_state_dict(payload["model_state"], strict=True)
    optimizer.load_state_dict(payload["optimizer_state"])
    scheduler.load_state_dict(payload["scheduler_state"])
    if scaler is not None and payload.get("scaler_state") is not None:
        scaler.load_state_dict(payload["scaler_state"])
    return {
        "sha256": actual_hash,
        "step": int(payload.get("step", 0)),
        "metadata": dict(payload.get("metadata", {})),
    }


def _rollout_for_task(
    model: TinyDecoderLM,
    task: GRPOTask,
    tokenizer: Any,
    config: GRPOConfig,
) -> Rollout:
    prompt_text = build_rollout_prompt_text(task)
    prompt_ids = tokenizer.encode(prompt_text, add_bos=True, add_eos=False)
    prompt_tensor = _truncate_prompt_ids(
        torch.tensor([prompt_ids], dtype=torch.long),
        model.config.max_sequence_length,
    )
    prompt_len = prompt_tensor.shape[1]
    generated_ids, _sampled_logprobs = sample_sequence(
        model,
        prompt_tensor,
        max_new_tokens=config.max_new_tokens,
        temperature=config.temperature,
        eos_token_id=tokenizer.eos_token_id,
    )
    generated_ids = generated_ids.detach().clone()
    decoded = tokenizer.decode(generated_ids[0, prompt_len:].tolist(), skip_special=True)
    raw_calls, final_answer = _parse_tool_calls(decoded)
    calls = tuple(
        ParsedToolCall(
            name=str(item.get("name", "")),
            arguments=item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
            valid=_call_is_valid(str(item.get("name", "")), item.get("arguments") if isinstance(item.get("arguments"), dict) else {}),
        )
        for item in raw_calls
    )
    reward = compute_reward(task, calls, final_answer, config)
    invalid_calls = sum(0 if call.valid else 1 for call in calls)
    over_steps = max(0, len(calls) - task.max_steps)
    return Rollout(
        task=task,
        prompt_len=prompt_len,
        generated_ids=generated_ids,
        decoded_text=decoded,
        calls=calls,
        final_answer=final_answer,
        reward=reward,
        invalid_calls=invalid_calls,
        over_steps=over_steps,
    )


def _evaluate_mean_reward(
    model: TinyDecoderLM,
    tasks: list[GRPOTask],
    tokenizer: Any,
    config: GRPOConfig,
    *,
    seed: int,
) -> dict[str, Any]:
    import random

    model.eval()
    if not tasks:
        raise ValueError("GRPO evaluation requires at least one task")
    selected = tasks[: min(len(tasks), max(1, config.eval_prompts))]
    rollouts = [_rollout_for_task(model, task, tokenizer, config) for task in selected]
    rewards = [rollout.reward for rollout in rollouts]
    total_calls = sum(len(rollout.calls) for rollout in rollouts)
    invalid_calls = sum(rollout.invalid_calls for rollout in rollouts)
    tool_correct = sum(
        1.0 if _tool_selection_correct(rollout.task, rollout.calls) else 0.0
        for rollout in rollouts
    )
    return {
        "mean_reward": sum(rewards) / len(rewards),
        "tool_selection_correct": tool_correct / len(rollouts),
        "invalid_call_rate": invalid_calls / total_calls if total_calls else 0.0,
        "rollout_count": len(rollouts),
    }


def train_grpo(
    model: TinyDecoderLM,
    moe_config: MoEConfig,
    config: GRPOConfig,
    *,
    tasks: list[GRPOTask],
    tokenizer: Any,
    artifact_dir: Path,
    resume_from: Path | None = None,
    pretrain_from: Path | None = None,
) -> GRPOResult:
    """Train Klara MoE with GRPO using frozen-policy rollout collection."""
    if not tasks:
        raise ValueError("GRPO training requires at least one task")
    seed_everything(config.seed)
    device = resolve_device(config.device)
    model.to(device)
    if pretrain_from is not None:
        load_pretrain_model_weights(pretrain_from, model=model)

    optimizer = _build_optimizer(model, config)
    scheduler = _build_scheduler(optimizer, config)
    context, scaler, effective_precision = _amp_context(device, config.precision)

    start_step = 0
    if resume_from is not None:
        restore = load_grpo_checkpoint(
            resume_from,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler if scaler.is_enabled() else None,
        )
        start_step = restore["step"]

    initial_eval = _evaluate_mean_reward(
        model,
        tasks,
        tokenizer,
        config,
        seed=config.seed + start_step,
    )
    logs: list[dict[str, Any]] = []
    gradients_finite = True
    final_policy_loss = 0.0
    last_checkpoint_hash = ""
    import random

    rng = random.Random(config.seed + 1000 + start_step)

    for step in range(start_step, config.steps):
        model.eval()
        prompt_tasks = [
            tasks[rng.randrange(len(tasks))] for _ in range(config.prompts_per_step)
        ]
        rollouts: list[Rollout] = []
        for task in prompt_tasks:
            for _ in range(config.group_size):
                rollouts.append(_rollout_for_task(model, task, tokenizer, config))
        _assign_advantages(rollouts, config.group_size)

        model.train()
        optimizer.zero_grad(set_to_none=True)
        policy_loss_sum = 0.0
        aux_loss_sum = 0.0
        for rollout in rollouts:
            log_probs = _sequence_logprobs(
                model,
                generated_ids=rollout.generated_ids,
                prompt_len=rollout.prompt_len,
            )
            sequence_logprob = log_probs.sum()
            policy_loss_sum += -(rollout.advantage * sequence_logprob)
            with context:
                aux_output = model(rollout.generated_ids)
            aux_loss_sum += aux_output.auxiliary_loss

        policy_loss = policy_loss_sum / len(rollouts)
        aux_loss = aux_loss_sum / len(rollouts)
        total_loss = policy_loss + config.auxiliary_loss_weight * aux_loss
        if not bool(torch.isfinite(total_loss)):
            raise FloatingPointError("non-finite GRPO total loss")
        scaler.scale(total_loss).backward()

        if scaler.is_enabled():
            scaler.unscale_(optimizer)
        step_gradients_finite = all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
        gradients_finite = gradients_finite and step_gradients_finite
        if not step_gradients_finite:
            raise FloatingPointError("non-finite GRPO model gradient")
        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            config.gradient_clip,
        )
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        final_policy_loss = float(policy_loss.detach().cpu().item())
        mean_reward = sum(rollout.reward for rollout in rollouts) / len(rollouts)
        current_lr = float(scheduler.get_last_lr()[0])
        completed_step = step + 1
        if completed_step % config.log_every == 0 or completed_step == config.steps:
            logs.append(
                {
                    "step": completed_step,
                    "mean_reward": mean_reward,
                    "policy_loss": final_policy_loss,
                    "auxiliary_loss": float(aux_loss.detach().cpu().item()),
                    "lr": current_lr,
                    "grad_norm": float(grad_norm),
                }
            )
        if config.checkpoint_every and completed_step % config.checkpoint_every == 0:
            last_checkpoint_hash = save_grpo_checkpoint(
                artifact_dir / f"checkpoint_{completed_step:07d}.pt",
                model=model,
                optimizer=optimizer,
                scheduler=scheduler,
                scaler=scaler if scaler.is_enabled() else None,
                step=completed_step,
                metadata={
                    "precision": effective_precision,
                    "num_experts": moe_config.num_experts,
                    "top_k": moe_config.top_k,
                },
            )

    final_eval = _evaluate_mean_reward(
        model,
        tasks,
        tokenizer,
        config,
        seed=config.seed + config.steps,
    )
    return GRPOResult(
        initial_mean_reward=initial_eval["mean_reward"],
        final_mean_reward=final_eval["mean_reward"],
        reward_change=final_eval["mean_reward"] - initial_eval["mean_reward"],
        final_policy_loss=final_policy_loss,
        gradients_finite=gradients_finite,
        parameter_count=count_parameters(model),
        final_step=config.steps,
        device=str(device),
        precision=effective_precision,
        logs=tuple(logs),
        model_state_sha256=model_state_sha256(model),
        final_checkpoint_sha256=last_checkpoint_hash,
    )





