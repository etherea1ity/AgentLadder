#!/usr/bin/env bash
#SBATCH --job-name=klara-lab-b
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/logs/lab-b-%j.log

set -euo pipefail

readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly ARTIFACT_DIR="${REMOTE_ROOT}/artifacts/lab-b-tiny-pretrain/job-${SLURM_JOB_ID}"

if [[ -z "${AGENTLADDER_SOURCE_DIR:-}" ]]; then
  echo "AGENTLADDER_SOURCE_DIR is required." >&2
  exit 2
fi
if [[ ! "${AGENTLADDER_SOURCE_BUNDLE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "AGENTLADDER_SOURCE_BUNDLE_SHA256 must be a lowercase SHA-256." >&2
  exit 2
fi
if [[ ! "${AGENTLADDER_PARENT_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "AGENTLADDER_PARENT_COMMIT must be a full Git commit." >&2
  exit 2
fi
source_dir="$(realpath "${AGENTLADDER_SOURCE_DIR}")"
case "${source_dir}" in
  /userhome/cs2/u3665453/AgentLadder/deployments/*) ;;
  *)
    echo "Refusing source outside the AgentLadder deployments directory: ${source_dir}" >&2
    exit 2
    ;;
esac
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing isolated Python environment: ${PYTHON_BIN}" >&2
  exit 3
fi

mkdir -p "${ARTIFACT_DIR}"
cd "${source_dir}"
export PYTHONPATH="${source_dir}/src"
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export CUDA_DEVICE_ORDER=PCI_BUS_ID

cat >"${ARTIFACT_DIR}/slurm.json" <<JSON
{
  "schema_version": "klara.hku-slurm.v1",
  "job_id": "${SLURM_JOB_ID}",
  "job_name": "${SLURM_JOB_NAME}",
  "node": "${SLURMD_NODENAME}",
  "partition": "${SLURM_JOB_PARTITION}",
  "source_dir": "${source_dir}",
  "source_bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}",
  "parent_commit": "${AGENTLADDER_PARENT_COMMIT}"
}
JSON

"${PYTHON_BIN}" --version
nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv,noheader

"${PYTHON_BIN}" - <<PY
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import tomllib

import torch

artifact_dir = Path("${ARTIFACT_DIR}")
source_dir = Path("${source_dir}")
config_path = source_dir / "config/experiments/lab_b_tiny_pretrain.toml"
corpus_path = source_dir / "tests/fixtures/algorithm/tiny_pretrain_corpus.txt"
config = tomllib.loads(config_path.read_text(encoding="utf-8"))
request = {
    "schema_version": "klara.training-run-request.v1",
    "created_at": datetime.now(UTC).isoformat(),
    "source": {
        "parent_commit": "${AGENTLADDER_PARENT_COMMIT}",
        "bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}",
        "deployment": "${source_dir}",
    },
    "slurm": {
        "job_id": "${SLURM_JOB_ID}",
        "node": "${SLURMD_NODENAME}",
        "partition": "${SLURM_JOB_PARTITION}",
    },
    "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    "data_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
    "seed": config["train"]["seed"],
    "precision": config["train"]["precision"],
    "scorer_version": "klara.pretrain-eval.v1",
    "hardware": {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unavailable",
        "vram_bytes": torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else 0,
    },
    "expected_artifacts": [
        "tiny_dense.pt",
        "manifest.json",
        "lab-b-tiny-pretrain.json",
        "lab-b-tiny-pretrain.md",
        "training-tests.log",
        "full-tests.log",
        "checksums.sha256",
    ],
}
assert request["hardware"]["cuda_available"] is True, request["hardware"]
(artifact_dir / "run-request.json").write_text(
    json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(request, ensure_ascii=False, sort_keys=True))
PY

"${PYTHON_BIN}" -m pytest tests/klara/training -q \
  | tee "${ARTIFACT_DIR}/training-tests.log"

"${PYTHON_BIN}" -m klara.training.cli pretrain \
  --config config/experiments/lab_b_tiny_pretrain.toml \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}" \
  --json-out "${ARTIFACT_DIR}/lab-b-tiny-pretrain.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-b-tiny-pretrain.md" \
  | tee "${ARTIFACT_DIR}/pretrain.stdout.json"

"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path

artifact_dir = Path("${ARTIFACT_DIR}")
report = json.loads((artifact_dir / "lab-b-tiny-pretrain.json").read_text(encoding="utf-8"))
assert report["passed"] is True, report["checks"]
assert all(report["checks"].values()), report["checks"]
print("lab_b_report_gate=PASS")
PY

"${PYTHON_BIN}" -m pytest -q | tee "${ARTIFACT_DIR}/full-tests.log"

(
  cd "${ARTIFACT_DIR}"
  sha256sum \
    tiny_dense.pt \
    manifest.json \
    lab-b-tiny-pretrain.json \
    lab-b-tiny-pretrain.md \
    slurm.json \
    run-request.json \
    pretrain.stdout.json \
    training-tests.log \
    full-tests.log \
    > checksums.sha256
)

nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "LAB_B_REMOTE_GATE=PASS"
