#!/usr/bin/env bash
#SBATCH --job-name=klara-moe-pretrain
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/klara-moe-pretrain-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/klara-moe-pretrain-%j.err

set -euo pipefail

readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly RUN_DIR="${REMOTE_ROOT}/runs/${SLURM_JOB_ID}"
readonly TOKENIZER_DIR="${REMOTE_ROOT}/artifacts/klara-moe-pretrain/tokenizer"
readonly SHARD_DIR="${REMOTE_ROOT}/artifacts/klara-moe-pretrain/packed"
readonly CORPUS_PATH="${KLARA_PRETRAIN_CORPUS:-${REMOTE_ROOT}/data/pretrain/klara_corpus.txt}"

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
[[ -f "${CORPUS_PATH}" ]] || { echo "Missing pretraining corpus: ${CORPUS_PATH}" >&2; exit 4; }

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
  "corpus_path": "${CORPUS_PATH}"
}
JSON

"${PYTHON_BIN}" --version
nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv,noheader

"${PYTHON_BIN}" -m klara.training.moe_pretrain_cli params \
  --config config/experiments/klara_moe_pretrain.toml \
  | tee "${RUN_DIR}/params.stdout.txt"

"${PYTHON_BIN}" -m klara.training.moe_pretrain_cli preprocess \
  --config config/experiments/klara_moe_pretrain.toml \
  --corpus "${CORPUS_PATH}" \
  --tokenizer-dir "${TOKENIZER_DIR}" \
  --output-dir "${SHARD_DIR}" \
  | tee "${RUN_DIR}/preprocess.stdout.json"

"${PYTHON_BIN}" -m klara.training.moe_pretrain_cli train \
  --config config/experiments/klara_moe_pretrain.toml \
  --shard-dir "${SHARD_DIR}" \
  --tokenizer-dir "${TOKENIZER_DIR}" \
  --artifact-dir "${RUN_DIR}" \
  | tee "${RUN_DIR}/train.stdout.json"

"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
run = Path("${RUN_DIR}")
result = json.loads((run / "result.json").read_text(encoding="utf-8"))
assert result["parameter_count"] == result["result"]["parameter_count"]
assert result["result"]["gradients_finite"] is True
assert result["result"]["final_step"] == result["train"]["steps"]
assert result["result"]["final_checkpoint_sha256"]
print("klara_moe_pretrain_gate=PASS")
PY

(
  cd "${RUN_DIR}"
  sha256sum \
    params.stdout.txt \
    preprocess.stdout.json \
    train.stdout.json \
    result.json \
    training_logs.jsonl \
    checkpoint_final.pt \
    slurm.json \
    > checksums.sha256
)

nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "KLARA_MOE_PRETRAIN_REMOTE_GATE=PASS"
