"""Repository-native four-expert top-2 token-level sparse MoE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from klara.training.config import ModelConfig
from klara.training.model import DenseFeedForward, FeedForwardOutput, TinyDecoderLM


MOE_SCORER_VERSION = "klara.tiny-moe-eval.v1"


@dataclass(frozen=True)
class MoEConfig:
    """Sparse-router settings fixed by the Gate 4 contract."""

    num_experts: int = 4
    top_k: int = 2
    auxiliary_loss_weight: float = 0.01
    z_loss_weight: float = 0.001

    def __post_init__(self) -> None:
        """Enforce the exact four-expert top-2 architecture."""

        if self.num_experts != 4 or self.top_k != 2:
            raise ValueError("Gate 4 requires exactly four experts and top-2 routing")
        if self.auxiliary_loss_weight <= 0 or self.z_loss_weight <= 0:
            raise ValueError("MoE auxiliary and z-loss weights must be positive")


class SparseMoE(nn.Module):
    """Dispatch each visible token to two distinct SwiGLU experts."""

    def __init__(self, model_config: ModelConfig, moe_config: MoEConfig) -> None:
        """Create a learned router and four independently parameterized experts."""

        super().__init__()
        self.model_config = model_config
        self.moe_config = moe_config
        self.router = nn.Linear(
            model_config.hidden_size,
            moe_config.num_experts,
            bias=False,
        )
        self.experts = nn.ModuleList(
            DenseFeedForward(model_config) for _ in range(moe_config.num_experts)
        )

    def forward(
        self,
        hidden_states: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> FeedForwardOutput:
        """Route visible tokens, combine top-2 outputs, and expose diagnostics."""

        if hidden_states.ndim != 3 or token_mask.shape != hidden_states.shape[:2]:
            raise ValueError("MoE expects [batch, sequence, hidden] plus token mask")
        flat_hidden = hidden_states.reshape(-1, hidden_states.shape[-1])
        flat_mask = token_mask.reshape(-1).bool()
        valid_hidden = flat_hidden[flat_mask]
        if valid_hidden.shape[0] == 0:
            raise ValueError("MoE requires at least one visible token")

        router_logits = self.router(valid_hidden).float()
        router_probabilities = F.softmax(router_logits, dim=-1)
        top_values, top_indices = torch.topk(
            router_logits,
            k=self.moe_config.top_k,
            dim=-1,
        )
        top_weights = F.softmax(top_values, dim=-1).to(valid_hidden.dtype)
        if bool(top_indices[:, 0].eq(top_indices[:, 1]).any()):
            raise RuntimeError("top-2 routing selected the same expert twice")

        combined = torch.zeros_like(valid_hidden)
        loads = torch.zeros(
            self.moe_config.num_experts,
            dtype=torch.float32,
            device=hidden_states.device,
        )
        valid_mask = torch.ones(
            (1, valid_hidden.shape[0]),
            dtype=torch.bool,
            device=hidden_states.device,
        )
        for expert_index, expert in enumerate(self.experts):
            selected_token, selected_slot = torch.where(top_indices == expert_index)
            loads[expert_index] = selected_token.numel()
            if selected_token.numel() == 0:
                continue
            expert_input = valid_hidden[selected_token].unsqueeze(0)
            expert_output = expert(expert_input, valid_mask[:, : selected_token.numel()])
            weighted = expert_output.hidden_states.squeeze(0) * top_weights[
                selected_token, selected_slot
            ].unsqueeze(-1)
            combined.index_add_(0, selected_token, weighted)

        output = torch.zeros_like(flat_hidden)
        output[flat_mask] = combined
        output = output.view_as(hidden_states)
        load_fraction = loads / loads.sum().clamp_min(1.0)
        importance = router_probabilities.mean(dim=0)
        balance_loss = self.moe_config.num_experts * torch.sum(
            importance * load_fraction
        )
        z_loss = torch.logsumexp(router_logits, dim=-1).square().mean()
        auxiliary_loss = (
            self.moe_config.auxiliary_loss_weight * balance_loss
            + self.moe_config.z_loss_weight * z_loss
        )
        entropy = -(
            router_probabilities
            * router_probabilities.clamp_min(torch.finfo(torch.float32).tiny).log()
        ).sum(dim=-1).mean()
        return FeedForwardOutput(
            hidden_states=output,
            auxiliary_loss=auxiliary_loss,
            routing_metrics={
                "expert_loads": loads,
                "router_entropy_sum": entropy,
                "router_z_loss_sum": z_loss,
                "router_balance_loss_sum": balance_loss,
                "selected_weight_sum_mean_sum": top_weights.float().sum(dim=-1).mean(),
                "routed_token_count": loads.sum() / self.moe_config.top_k,
            },
        )


def build_moe_model(model_config: ModelConfig, moe_config: MoEConfig) -> TinyDecoderLM:
    """Create a tiny decoder whose every feed-forward block is sparse MoE."""

    return TinyDecoderLM(
        model_config,
        feed_forward_factory=lambda config, _layer: SparseMoE(config, moe_config),
    )


def routing_diagnostics(
    model: TinyDecoderLM,
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Evaluate aggregate route load, entropy, and collapse on a token fixture."""

    model.to(device).eval()
    with torch.inference_mode():
        output = model(
            input_ids.to(device),
            attention_mask=attention_mask.to(device),
        )
    metrics = output.routing_metrics
    loads = metrics["expert_loads"].detach().cpu().float()
    layer_count = len(model.blocks)
    minimum_load = float(loads.min().item())
    maximum_load = float(loads.max().item())
    ratio = maximum_load / minimum_load if minimum_load > 0 else float("inf")
    entropy = float(metrics["router_entropy_sum"].item()) / layer_count
    selected_sum = float(metrics["selected_weight_sum_mean_sum"].item()) / layer_count
    return {
        "expert_loads": [int(value) for value in loads.tolist()],
        "minimum_expert_load": int(minimum_load),
        "maximum_expert_load": int(maximum_load),
        "max_min_load_ratio": ratio,
        "router_entropy": entropy,
        "selected_weight_sum_mean": selected_sum,
        "all_experts_used": minimum_load > 0,
        "collapse_detected": minimum_load == 0 or ratio > 2.0,
        "router_z_loss": float(metrics["router_z_loss_sum"].item()) / layer_count,
        "router_balance_loss": float(metrics["router_balance_loss_sum"].item()) / layer_count,
    }


def balanced_router_probe(
    model: TinyDecoderLM,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Probe every trained router with balanced target logits in router space."""

    model.to(device).eval()
    aggregate_loads = torch.zeros(4, dtype=torch.float32, device=device)
    entropies: list[float] = []
    weight_sums: list[float] = []
    pairs = ((0, 1), (1, 2), (2, 3), (3, 0))
    for block in model.blocks:
        moe = block.feed_forward
        if not isinstance(moe, SparseMoE):
            raise TypeError("balanced_router_probe requires SparseMoE blocks")
        target_logits = torch.full((8, 4), -4.0, device=device)
        for row in range(8):
            first, second = pairs[row % len(pairs)]
            target_logits[row, first] = 4.0
            target_logits[row, second] = 3.0
        router_weight = moe.router.weight.float()
        hidden = target_logits @ torch.linalg.pinv(router_weight.T)
        with torch.inference_mode():
            result = moe(
                hidden.to(next(moe.parameters()).dtype).unsqueeze(0),
                torch.ones((1, hidden.shape[0]), dtype=torch.bool, device=device),
            )
        aggregate_loads += result.routing_metrics["expert_loads"]
        entropies.append(float(result.routing_metrics["router_entropy_sum"].item()))
        weight_sums.append(
            float(result.routing_metrics["selected_weight_sum_mean_sum"].item())
        )
    minimum = float(aggregate_loads.min().item())
    maximum = float(aggregate_loads.max().item())
    ratio = maximum / minimum if minimum > 0 else float("inf")
    return {
        "expert_loads": [int(value) for value in aggregate_loads.cpu().tolist()],
        "all_experts_used": minimum > 0,
        "max_min_load_ratio": ratio,
        "router_entropy": sum(entropies) / len(entropies),
        "selected_weight_sum_mean": sum(weight_sums) / len(weight_sums),
        "collapse_detected": minimum == 0 or ratio > 2.0,
    }
