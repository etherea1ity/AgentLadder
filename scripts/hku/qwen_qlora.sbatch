#!/usr/bin/env bash
#SBATCH --job-name=qwen-qlora-sft
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/logs/qwen-qlora-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/logs/qwen-qlora-%j.err

set -euo pipefail

readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly ARTIFACT_DIR="${REMOTE_ROOT}/artifacts/qwen-qlora-sft/job-${SLURM_JOB_ID}"
readonly RUN_DIR="${REMOTE_ROOT}/runs/qwen-qlora-sft/${SLURM_JOB_ID}"

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
    echo "Refusing source outside HKU deployments: ${source_dir}" >&2
    exit 2
    ;;
esac

[[ -x "${PYTHON_BIN}" ]] || { echo "Missing isolated Python environment." >&2; exit 3; }

mkdir -p "${ARTIFACT_DIR}" "${RUN_DIR}"
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
  "artifact_dir": "${ARTIFACT_DIR}"
}
JSON

"${PYTHON_BIN}" --version
nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv,noheader

"${PYTHON_BIN}" -m klara.qwen.qlora_sft validate-config \
  --config config/experiments/qwen_qlora.toml \
  | tee "${RUN_DIR}/validate-config.stdout.json"

"${PYTHON_BIN}" -m klara.qwen.qlora_sft train \
  --config config/experiments/qwen_qlora.toml \
  --output-dir "${ARTIFACT_DIR}" \
  | tee "${RUN_DIR}/train.stdout.json"

"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
run = Path("${RUN_DIR}")
artifact = Path("${ARTIFACT_DIR}")
summary = json.loads((artifact / "run_summary.json").read_text(encoding="utf-8"))
assert summary["output_dir"] == str(artifact)
assert (artifact / "adapter_config.json").exists()
assert (artifact / "adapter_model.safetensors").exists() or (artifact / "adapter_model.bin").exists()
print("qwen_qlora_sft_gate=PASS")
PY

(
  cd "${RUN_DIR}"
  sha256sum slurm.json validate-config.stdout.json train.stdout.json > checksums.sha256
)
(
  cd "${ARTIFACT_DIR}"
  sha256sum run_summary.json adapter_config.json adapter_model.safetensors > checksums.sha256 2>/dev/null || true
)

nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "QWEN_QLORA_REMOTE_GATE=PASS"