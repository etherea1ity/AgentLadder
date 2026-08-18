"""Local inference-optimization lane for the Klara sparse MoE model."""

from klara.inference.kv_cache import GQAKVCache, generate_with_cache
from klara.inference.w4a16 import benchmark_w4a16

__all__ = [
    "GQAKVCache",
    "benchmark_w4a16",
    "generate_with_cache",
]
