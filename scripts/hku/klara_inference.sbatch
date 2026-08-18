#!/usr/bin/env bash
#SBATCH --job-name=klara-inference
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/klara-inference-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/klara-inference-%j.err

set -euo pipefail

readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly CHECKPOINT="${KLARA_INFERENCE_CHECKPOINT:-${REMOTE_ROOT}/artifacts/klara-moe-pretrain/checkpoint_final.pt}"
readonly RUN_DIR="${REMOTE_ROOT}/runs/klara-inference-${SLURM_JOB_ID}"

if [[ -z "${AGENTLADDER_SOURCE_DIR:-}" \
  || ! "${AGENTLADDER_SOURCE_BUNDLE_SHA256:-}" =~ ^[0-9a-f]{64}$ \
  || ! "${AGENTLADDER_PARENT_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Complete source lineage is required." >&2
  exit 2
fi

source_dir="$(realpath "${AGENTLADDER_SOURCE_DIR}")"
case "${source_dir}" in
  /userhome/cs2/u3665453/AgentLadder/deployments/*) ;;
  *)
    echo "Refusing source outside HKU deployments." >&2
    exit 2
    ;;
esac

[[ -x "${PYTHON_BIN}" ]] || { echo "Missing isolated Python." >&2; exit 3; }
[[ -f "${CHECKPOINT}" ]] || { echo "Missing inference checkpoint: ${CHECKPOINT}" >&2; exit 4; }

mkdir -p "${REMOTE_ROOT}/runs" "${RUN_DIR}"
cd "${source_dir}"
export PYTHONPATH="${source_dir}/src"
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export CUDA_DEVICE_ORDER=PCI_BUS_ID

cat >"${RUN_DIR}/slurm.json" <<JSON
{
  "schema_version": "klara.hku-slurm.v1",
  "job_id": "${SLURM_JOB_ID}",
  "job_name": "${SLURM_JOB_NAME}",
  "node": "${SLURMD_NODENAME}",
  "partition": "${SLURM_JOB_PARTITION}",
  "source_dir": "${source_dir}",
  "source_bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}",
  "parent_commit": "${AGENTLADDER_PARENT_COMMIT}",
  "run_dir": "${RUN_DIR}",
  "checkpoint": "${CHECKPOINT}"
}
JSON

"${PYTHON_BIN}" --version
nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv,noheader

"${PYTHON_BIN}" -m pytest src/klara/inference/test_kv_cache.py -q \
  | tee "${RUN_DIR}/kv-cache-tests.log"

"${PYTHON_BIN}" -m klara.inference.bench_cli "${CHECKPOINT}" \
  --config config/inference.toml \
  --json-out "${RUN_DIR}/bench.json" \
  | tee "${RUN_DIR}/bench.stdout.json"

"${PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path

run_dir = Path("${RUN_DIR}")
bench = json.loads((run_dir / "bench.json").read_text(encoding="utf-8"))
assert bench["schema_version"] == "klara.inference.bench.v1"
assert bench["benchmark"]["bench_runs"] >= 1
assert bench["benchmark"]["p95_prefill_ttft_ms"] >= 0.0
assert bench["benchmark"]["tokens_per_second"] >= 0.0
if bench["w4a16"] is not None:
    assert bench["w4a16"]["storage"]["fp4_storage_bytes"] < bench["w4a16"]["storage"]["fp16_baseline_bytes"]
print("klara_inference_bench_gate=PASS")
PY

(
  cd "${RUN_DIR}"
  sha256sum \
    slurm.json \
    kv-cache-tests.log \
    bench.stdout.json \
    bench.json \
    > checksums.sha256
)

nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "KLARA_INFERENCE_REMOTE_GATE=PASS"
