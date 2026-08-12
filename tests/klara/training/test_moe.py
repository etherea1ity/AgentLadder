from __future__ import annotations

import torch

from klara.training.checkpoint import load_checkpoint, save_checkpoint
from klara.training.config import ModelConfig
from klara.training.moe import (
    MoEConfig,
    SparseMoE,
    balanced_router_probe,
    build_moe_model,
    routing_diagnostics,
)
from klara.training.trainer import model_state_sha256


def _config() -> ModelConfig:
    return ModelConfig(
        hidden_size=16,
        num_layers=2,
        num_attention_heads=2,
        num_key_value_heads=1,
        intermediate_size=32,
        max_sequence_length=16,
    )


def test_moe_requires_exactly_four_experts_and_top_two() -> None:
    for kwargs in ({"num_experts": 3}, {"top_k": 1}):
        try:
            MoEConfig(**kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover - assertion branch
            raise AssertionError("invalid MoE configuration was accepted")


def test_token_level_top_two_are_distinct_and_weights_sum_to_one() -> None:
    torch.manual_seed(4)
    moe = SparseMoE(_config(), MoEConfig())
    hidden = torch.randn(2, 5, 16, requires_grad=True)
    mask = torch.tensor(
        [[True, True, True, False, False], [True, True, True, True, False]]
    )

    result = moe(hidden, mask)
    result.hidden_states.square().mean().add(result.auxiliary_loss).backward()

    assert result.hidden_states.shape == hidden.shape
    assert torch.all(result.hidden_states[~mask].eq(0))
    assert torch.isfinite(result.auxiliary_loss)
    assert float(result.auxiliary_loss) > 0
    assert torch.allclose(
        result.routing_metrics["selected_weight_sum_mean_sum"],
        torch.tensor(1.0),
        atol=1e-6,
    )
    assert int(result.routing_metrics["expert_loads"].sum().item()) == int(mask.sum()) * 2
    assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in moe.parameters())


def test_balanced_probe_uses_every_expert_without_collapse() -> None:
    torch.manual_seed(5)
    model = build_moe_model(_config(), MoEConfig())

    report = balanced_router_probe(model, device=torch.device("cpu"))

    assert report["all_experts_used"] is True
    assert report["max_min_load_ratio"] <= 2.0
    assert report["collapse_detected"] is False
    assert abs(report["selected_weight_sum_mean"] - 1.0) <= 1e-6


def test_full_moe_model_forward_backward_and_routing_metrics_are_finite() -> None:
    torch.manual_seed(6)
    model = build_moe_model(_config(), MoEConfig())
    tokens = torch.randint(4, 260, (2, 12))
    mask = torch.ones_like(tokens, dtype=torch.bool)
    labels = tokens.roll(-1, dims=1)

    output = model(tokens, attention_mask=mask, labels=labels)
    assert output.loss is not None
    output.loss.backward()
    diagnostics = routing_diagnostics(model, tokens, mask, device=torch.device("cpu"))

    assert torch.isfinite(output.loss)
    assert output.auxiliary_loss is not None and float(output.auxiliary_loss) > 0
    assert diagnostics["router_entropy"] > 0
    assert abs(diagnostics["selected_weight_sum_mean"] - 1.0) <= 1e-6
    assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in model.parameters())


def test_moe_checkpoint_strict_reload_preserves_router_and_experts(tmp_path) -> None:
    torch.manual_seed(7)
    model = build_moe_model(_config(), MoEConfig())
    path = tmp_path / "moe.pt"
    checkpoint_hash = save_checkpoint(
        path,
        model=model,
        optimizer=None,
        step=3,
        metadata={"experts": 4, "top_k": 2},
    )
    restored = build_moe_model(_config(), MoEConfig())

    details = load_checkpoint(path, model=restored, expected_sha256=checkpoint_hash)

    assert details["step"] == 3
    assert model_state_sha256(restored) == model_state_sha256(model)
