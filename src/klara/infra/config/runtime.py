"""Typed runtime execution configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from klara.core.policies import LoopPolicy
from klara.context.policy import ContextPolicy


@dataclass(frozen=True)
class ProviderRecoveryPolicy:
    """Secret-free provider retry and timeout policy frozen per product run."""

    timeout_seconds: int | None = None
    retry_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 8.0
    retry_jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds < 1:
            raise ValueError("provider timeout must be positive when provided")
        if self.retry_attempts < 1:
            raise ValueError("provider retry attempts must be at least 1")
        if self.retry_base_delay_seconds < 0 or self.retry_max_delay_seconds < 0:
            raise ValueError("provider retry delays must be non-negative")
        if self.retry_max_delay_seconds < self.retry_base_delay_seconds:
            raise ValueError("provider retry max delay must cover the base delay")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("provider retry jitter ratio must be between 0 and 1")

    def to_public_dict(self) -> dict[str, int | float | None]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "retry_attempts": self.retry_attempts,
            "retry_base_delay_seconds": self.retry_base_delay_seconds,
            "retry_max_delay_seconds": self.retry_max_delay_seconds,
            "retry_jitter_ratio": self.retry_jitter_ratio,
        }


@dataclass(frozen=True)
class CapabilityProfile:
    """Frozen product capability selection used before a run is assembled."""

    id: str
    required_model_capabilities: tuple[str, ...] = ("tools",)
    visible_tools: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ("jsonl_trace",)
    trace_sink: str = "jsonl"

    def __post_init__(self) -> None:
        """Reject unknown capabilities and trace sinks at config-load time."""

        known = {"tools", "json", "vision", "thinking"}
        unknown = sorted(set(self.required_model_capabilities) - known)
        if unknown:
            raise ValueError(f"unknown model capabilities: {unknown}")
        if self.trace_sink not in {"none", "jsonl"}:
            raise ValueError("trace_sink must be 'none' or 'jsonl'")


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime policy configuration for assembling Klara runs."""

    # Loop policy controls model/tool iteration bounds.
    loop_policy: LoopPolicy = field(default_factory=LoopPolicy)
    context_policy: ContextPolicy = field(default_factory=ContextPolicy)
    provider_recovery_policy: ProviderRecoveryPolicy = field(
        default_factory=ProviderRecoveryPolicy
    )
    default_capability_profile: str = "agent"
    capability_profiles: tuple[CapabilityProfile, ...] = (
        CapabilityProfile(id="agent"),
    )

    def profile(self, profile_id: str | None = None) -> CapabilityProfile:
        """Return one immutable capability profile by id."""

        selected = profile_id or self.default_capability_profile
        for profile in self.capability_profiles:
            if profile.id == selected:
                return profile
        raise KeyError(selected)
