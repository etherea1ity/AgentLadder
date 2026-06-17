"""Registries for Chapter 3 controlled capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from agent_ladder.rag.contracts.agentic import CapabilitySpec, SearchProviderSpec, WorkerAgentSpec

T = TypeVar("T")


@dataclass
class _Registry(Generic[T]):
    _items: dict[str, T] = field(default_factory=dict)

    def register(self, key: str, value: T) -> None:
        if key in self._items:
            raise ValueError(f"duplicate registry key: {key}")
        self._items[key] = value

    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(f"unknown registry key: {key}") from None

    def list(self) -> list[T]:
        return list(self._items.values())

    def has(self, key: str) -> bool:
        return key in self._items


class CapabilityRegistry(_Registry[CapabilitySpec]):
    def register_spec(self, spec: CapabilitySpec) -> None:
        self.register(spec.capability_id, spec)


class WorkerAgentRegistry(_Registry[WorkerAgentSpec]):
    def register_spec(self, spec: WorkerAgentSpec) -> None:
        self.register(spec.worker_id, spec)


class SearchProviderRegistry(_Registry[SearchProviderSpec]):
    def register_spec(self, spec: SearchProviderSpec) -> None:
        self.register(spec.provider_id, spec)
