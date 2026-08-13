"""Payload-free counters for the authenticated production surface."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class MetricSnapshot:
    requests: dict[str, int]
    failures: dict[str, int]
    latency_ms_total: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "klara.production-metrics.v1",
            "requests": dict(sorted(self.requests.items())),
            "failures": dict(sorted(self.failures.items())),
            "latency_ms_total": dict(sorted(self.latency_ms_total.items())),
        }


class SafeRuntimeMetrics:
    """Aggregate only route templates, methods, status classes, and timings."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()
        self._latency: defaultdict[str, int] = defaultdict(int)

    def observe(self, *, method: str, route: str, status_code: int, latency_ms: int) -> None:
        key = f"{method.upper()} {route} {status_code // 100}xx"
        with self._lock:
            self._requests[key] += 1
            self._latency[key] += max(0, int(latency_ms))
            if status_code >= 400:
                self._failures[key] += 1

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            return MetricSnapshot(
                requests=dict(self._requests),
                failures=dict(self._failures),
                latency_ms_total=dict(self._latency),
            )
