"""Typed runtime execution configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from klara.core.policies import LoopPolicy


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
