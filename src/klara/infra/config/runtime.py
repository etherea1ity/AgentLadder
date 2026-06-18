"""Typed runtime execution configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from klara.core.policies import LoopPolicy


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime policy configuration for assembling Klara runs."""

    # Loop policy controls model/tool iteration bounds.
    loop_policy: LoopPolicy = field(default_factory=LoopPolicy)
