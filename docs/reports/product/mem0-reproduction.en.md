# Mem0 Reproduction Status

Language: [Chinese](./mem0-reproduction.md) | English

The pinned official `memory-benchmarks` Mem0 Dockerfile references the deleted `feat/v3-pipeline` branch, so its container cannot be built byte-for-byte from that commit. This stage claims no Mem0 score and does not present the current SDK compatibility adapter as official execution.

The next valid run must pin a corrected official image or vendor the deleted implementation with complete provenance, then use the identical LoCoMo subset, answer model, generation budget, and scorer.
