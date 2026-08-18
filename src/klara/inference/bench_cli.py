"""Command-line inference benchmark for Klara MoE checkpoints.

The benchmark is deliberately local-first: it can run on CPU for small random
models and on a CUDA device for the real pretrained checkpoints.  It measures
prefill TTFT, cached decode tokens/s, and peak memory, then emits a single JSON
document.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import sys
import time
import tomllib
from typing import Any

import torch

from klara.inference.kv_cache import GQAKVCache
from klara.inference.w4a16 import benchmark_w4a16
from klara.training.checkpoint import CHECKPOINT_FORMAT
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig, build_moe_model
from klara.training.model import TinyDecoderLM
from klara.training.moe_pretrain import MOE_PRETRAIN_CHECKPOINT_FORMAT

BENCH_SCHEMA_VERSION = "klara.inference.bench.v1"
DEFAULT_CONFIG_PATH = "config/inference.toml"


@dataclass(frozen=True)
class InferenceBenchConfig:
    """Validated benchmark settings loaded from ``config/inference.toml``."""

    checkpoint: str = ""
    device: str = "auto"
    input_len: int = 32
    batch_size: int = 1
    max_new_tokens: int = 16
    warmup_runs: int = 1
    bench_runs: int = 5
    seed: int = 20260816
    w4a16_enabled: bool = True
    block_size: int = 64
    json_out: str = ""

    def __post_init__(self) -> None:
        """Reject nonsensical local benchmark settings."""

        if self.input_len < 1 or self.batch_size < 1:
            raise ValueError("input_len and batch_size must be positive")
        if self.max_new_tokens < 0:
            raise ValueError("max_new_tokens must be non-negative")
        if self.warmup_runs < 0 or self.bench_runs < 1:
            raise ValueError("warmup_runs must be >= 0 and bench_runs >= 1")
        if self.block_size < 2:
            raise ValueError("block_size must be at least 2")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu, or cuda")

    @classmethod
    def from_toml(cls, path: Path | str) -> "InferenceBenchConfig":
        """Read benchmark, w4a16, and output sections from TOML."""

        path = Path(path)
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        benchmark = raw.get("benchmark", {})
        w4a16 = raw.get("w4a16", {})
        output = raw.get("output", {})
        return cls(
            checkpoint=str(benchmark.get("checkpoint", "")),
            device=str(benchmark.get("device", "auto")),
            input_len=int(benchmark.get("input_len", 32)),
            batch_size=int(benchmark.get("batch_size", 1)),
            max_new_tokens=int(benchmark.get("max_new_tokens", 16)),
            warmup_runs=int(benchmark.get("warmup_runs", 1)),
            bench_runs=int(benchmark.get("bench_runs", 5)),
            seed=int(benchmark.get("seed", 20260816)),
            w4a16_enabled=bool(w4a16.get("enabled", True)),
            block_size=int(w4a16.get("block_size", 64)),
            json_out=str(output.get("json_path", "")),
        )


def resolve_device(spec: str) -> torch.device:
    """Resolve ``auto`` to CUDA when available, otherwise CPU."""

    if spec == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(spec)


def _load_checkpoint_payload(path: Path) -> dict[str, Any]:
    """Load a training checkpoint without constructing optimizer state."""

    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict):
        raise ValueError("checkpoint payload must be a dictionary")
    if "format" not in payload or "model_config" not in payload or "model_state" not in payload:
        raise ValueError("checkpoint is missing required fields")
    return payload


def build_model_from_checkpoint(path: Path) -> tuple[TinyDecoderLM, dict[str, Any]]:
    """Build and restore a dense or sparse-MoE model from a checkpoint."""

    payload = _load_checkpoint_payload(path)
    model_config = ModelConfig.from_dict(dict(payload["model_config"]))
    checkpoint_format = payload["format"]
    if checkpoint_format == MOE_PRETRAIN_CHECKPOINT_FORMAT:
        metadata = dict(payload.get("metadata", {}))
        moe_config = MoEConfig(
            num_experts=int(metadata.get("num_experts", 4)),
            top_k=int(metadata.get("top_k", 2)),
            auxiliary_loss_weight=float(metadata.get("auxiliary_loss_weight", 0.01)),
            z_loss_weight=float(metadata.get("z_loss_weight", 0.001)),
        )
        model = build_moe_model(model_config, moe_config)
    elif checkpoint_format == CHECKPOINT_FORMAT:
        model = TinyDecoderLM(model_config)
    else:
        raise ValueError(f"unsupported checkpoint format: {checkpoint_format}")
    model.load_state_dict(payload["model_state"], strict=True)
    return model, {
        "format": checkpoint_format,
        "step": payload.get("step"),
        "metadata": payload.get("metadata", {}),
        "model_config": model_config.to_dict(),
    }


def _synthetic_input_ids(
    model: TinyDecoderLM,
    *,
    batch_size: int,
    input_len: int,
    seed: int,
    device: torch.device,
) -> torch.Tensor:
    """Create token ids that avoid pad/bos/eos special rows."""

    excluded = {
        int(model.config.pad_token_id),
        int(model.config.bos_token_id),
        int(model.config.eos_token_id),
    }
    allowed = torch.tensor(
        [index for index in range(model.config.vocab_size) if index not in excluded],
        dtype=torch.long,
    )
    if allowed.numel() < 2:
        raise ValueError("vocabulary has too few non-special tokens")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    indices = torch.randint(
        0,
        allowed.numel(),
        (batch_size, input_len),
        generator=generator,
    )
    return allowed[indices].to(device)


def _synchronize(device: torch.device) -> None:
    """Synchronize CUDA work; no-op on CPU."""

    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _peak_memory_bytes(device: torch.device) -> int:
    """Return CUDA peak allocated bytes, or best-effort CPU RSS."""

    if device.type == "cuda":
        return int(torch.cuda.max_memory_allocated(device))
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return 0


def _measure_once(
    model: TinyDecoderLM,
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
    *,
    device: torch.device,
    max_new_tokens: int,
) -> dict[str, float]:
    """Run one prefill + cached decode repetition and return timing/peak data."""

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    cache = GQAKVCache(model)
    _synchronize(device)
    start = time.perf_counter()
    output = cache.prefill(model, input_ids, attention_mask=attention_mask)
    _synchronize(device)
    prefill_seconds = time.perf_counter() - start

    batch_size = input_ids.shape[0]
    next_token = output.logits[:, -1].argmax(dim=-1, keepdim=True)
    decode_tokens = 0
    start = time.perf_counter()
    for _ in range(max_new_tokens):
        output = cache.decode(
            model,
            next_token,
            attention_mask=torch.ones(
                (batch_size, 1),
                dtype=torch.bool,
                device=input_ids.device,
            ),
        )
        next_token = output.logits[:, -1].argmax(dim=-1, keepdim=True)
        decode_tokens += 1
    _synchronize(device)
    decode_seconds = time.perf_counter() - start

    return {
        "prefill_seconds": float(prefill_seconds),
        "decode_seconds": float(decode_seconds),
        "decode_tokens": float(decode_tokens),
        "peak_memory_bytes": float(_peak_memory_bytes(device)),
    }


def _percentile(values: list[float], quantile: float) -> float:
    """Return the nearest-rank percentile without external dependencies."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, int(math.ceil(quantile * len(ordered)) - 1)))
    return ordered[rank]


def _json_safe(value: Any) -> Any:
    """Recursively convert PyTorch/path values to JSON-compatible types."""

    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except (ValueError, RuntimeError):
            pass
    return value


def run_benchmark(
    checkpoint_path: Path,
    config: InferenceBenchConfig,
) -> dict[str, Any]:
    """Execute the local inference benchmark and return a JSON-ready result."""

    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"checkpoint not found: {checkpoint_path}")

    model, checkpoint_info = build_model_from_checkpoint(checkpoint_path)
    device = resolve_device(config.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    model.to(device).eval()

    total_length = config.input_len + config.max_new_tokens
    if total_length > model.config.max_sequence_length:
        raise ValueError(
            "input_len + max_new_tokens exceeds model.max_sequence_length: "
            f"{total_length} > {model.config.max_sequence_length}"
        )

    prefill_ttft_ms: list[float] = []
    run_stats: list[dict[str, float]] = []
    total_decode_tokens = 0.0
    total_decode_seconds = 0.0
    cpu_peak_bytes = 0

    for run_index in range(config.warmup_runs):
        input_ids = _synthetic_input_ids(
            model,
            batch_size=config.batch_size,
            input_len=config.input_len,
            seed=config.seed + run_index,
            device=device,
        )
        attention_mask = input_ids.ne(model.config.pad_token_id)
        _measure_once(
            model,
            input_ids,
            attention_mask,
            device=device,
            max_new_tokens=config.max_new_tokens,
        )

    for run_index in range(config.bench_runs):
        input_ids = _synthetic_input_ids(
            model,
            batch_size=config.batch_size,
            input_len=config.input_len,
            seed=config.seed + config.warmup_runs + run_index,
            device=device,
        )
        attention_mask = input_ids.ne(model.config.pad_token_id)
        stats = _measure_once(
            model,
            input_ids,
            attention_mask,
            device=device,
            max_new_tokens=config.max_new_tokens,
        )
        prefill_ttft_ms.append(stats["prefill_seconds"] * 1000.0)
        run_stats.append(stats)
        total_decode_tokens += stats["decode_tokens"]
        total_decode_seconds += stats["decode_seconds"]
        if device.type == "cpu":
            cpu_peak_bytes = max(cpu_peak_bytes, int(stats["peak_memory_bytes"]))

    peak_memory_bytes = (
        int(max(item["peak_memory_bytes"] for item in run_stats))
        if device.type == "cuda"
        else cpu_peak_bytes
    )
    mean_prefill_ms = (
        float(statistics.fmean(prefill_ttft_ms)) if prefill_ttft_ms else 0.0
    )
    p95_prefill_ms = _percentile(prefill_ttft_ms, 0.95)
    tokens_per_second = (
        total_decode_tokens / total_decode_seconds
        if total_decode_seconds > 0
        else 0.0
    )

    sample_input_ids = _synthetic_input_ids(
        model,
        batch_size=config.batch_size,
        input_len=config.input_len,
        seed=config.seed,
        device=device,
    )
    w4a16_result: dict[str, Any] | None = None
    if config.w4a16_enabled:
        w4a16_result = benchmark_w4a16(
            model,
            sample_input_ids,
            attention_mask=sample_input_ids.ne(model.config.pad_token_id),
            block_size=config.block_size,
        )

    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    result: dict[str, Any] = {
        "schema_version": BENCH_SCHEMA_VERSION,
        "checkpoint": {
            "path": str(checkpoint_path),
            "format": checkpoint_info["format"],
            "step": checkpoint_info["step"],
            "metadata": checkpoint_info["metadata"],
        },
        "model": {
            "parameter_count": int(parameter_count),
            "config": checkpoint_info["model_config"],
        },
        "hardware": {
            "device": device.type,
            "torch": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "gpu_name": (
                torch.cuda.get_device_name(device)
                if device.type == "cuda" and torch.cuda.is_available()
                else "unavailable"
            ),
        },
        "benchmark": {
            "warmup_runs": config.warmup_runs,
            "bench_runs": config.bench_runs,
            "batch_size": config.batch_size,
            "input_len": config.input_len,
            "max_new_tokens": config.max_new_tokens,
            "prefill_ttft_ms": [round(value, 6) for value in prefill_ttft_ms],
            "mean_prefill_ttft_ms": round(mean_prefill_ms, 6),
            "p95_prefill_ttft_ms": round(p95_prefill_ms, 6),
            "decode_tokens": int(total_decode_tokens),
            "decode_seconds": round(total_decode_seconds, 6),
            "tokens_per_second": round(tokens_per_second, 6),
            "peak_memory_bytes": peak_memory_bytes,
        },
        "w4a16": w4a16_result,
        "generated_token_count": int(total_decode_tokens),
    }
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a Klara MoE checkpoint")
    parser.add_argument("checkpoint", nargs="?", default=None, help="checkpoint .pt path")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--json-out", default=None, help="optional JSON output path")
    parser.add_argument("--device", default=None, choices=["auto", "cpu", "cuda"])
    parser.add_argument("--input-len", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument("--warmup-runs", type=int, default=None)
    parser.add_argument("--bench-runs", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--block-size", type=int, default=None)
    parser.add_argument(
        "--w4a16",
        dest="w4a16",
        action="store_true",
        default=None,
        help="enable W4A16 precision/storage benchmark",
    )
    parser.add_argument(
        "--no-w4a16",
        dest="w4a16",
        action="store_false",
        help="disable W4A16 precision/storage benchmark",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and write JSON to stdout and an optional file."""

    args = _parse_args(argv)
    config_path = Path(args.config)
    if config_path.is_file():
        config = InferenceBenchConfig.from_toml(config_path)
    else:
        config = InferenceBenchConfig()

    checkpoint = args.checkpoint or config.checkpoint
    if not checkpoint:
        print(
            "error: a checkpoint is required (positional argument or "
            "checkpoint in config/inference.toml)",
            file=sys.stderr,
        )
        return 2

    config = InferenceBenchConfig(
        checkpoint=str(checkpoint),
        device=args.device or config.device,
        input_len=args.input_len if args.input_len is not None else config.input_len,
        batch_size=args.batch_size if args.batch_size is not None else config.batch_size,
        max_new_tokens=(
            args.max_new_tokens
            if args.max_new_tokens is not None
            else config.max_new_tokens
        ),
        warmup_runs=(
            args.warmup_runs if args.warmup_runs is not None else config.warmup_runs
        ),
        bench_runs=args.bench_runs if args.bench_runs is not None else config.bench_runs,
        seed=args.seed if args.seed is not None else config.seed,
        w4a16_enabled=(
            args.w4a16 if args.w4a16 is not None else config.w4a16_enabled
        ),
        block_size=args.block_size if args.block_size is not None else config.block_size,
        json_out=args.json_out or config.json_out,
    )

    result = run_benchmark(Path(config.checkpoint), config)
    safe_result = _json_safe(result)
    rendered = json.dumps(safe_result, indent=2, sort_keys=True) + "\n"
    print(rendered)
    if config.json_out:
        output_path = Path(config.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
