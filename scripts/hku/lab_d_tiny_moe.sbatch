#!/usr/bin/env bash
#SBATCH --job-name=klara-lab-d
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/logs/lab-d-%j.log

set -euo pipefail
readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly ARTIFACT_DIR="${REMOTE_ROOT}/artifacts/lab-d-tiny-moe/job-${SLURM_JOB_ID}"
if [[ -z "${AGENTLADDER_SOURCE_DIR:-}" \
  || ! "${AGENTLADDER_SOURCE_BUNDLE_SHA256:-}" =~ ^[0-9a-f]{64}$ \
  || ! "${AGENTLADDER_PARENT_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Complete source lineage is required." >&2
  exit 2
fi
source_dir="$(realpath "${AGENTLADDER_SOURCE_DIR}")"
case "${source_dir}" in
  /userhome/cs2/u3665453/AgentLadder/deployments/*) ;;
  *) echo "Refusing source outside HKU deployments." >&2; exit 2 ;;
esac
[[ -x "${PYTHON_BIN}" ]] || { echo "Missing isolated Python." >&2; exit 3; }
mkdir -p "${ARTIFACT_DIR}"
cd "${source_dir}"
export PYTHONPATH="${source_dir}/src"
export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false CUDA_DEVICE_ORDER=PCI_BUS_ID
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
import hashlib, json, platform, tomllib
from pathlib import Path
import torch
artifact = Path("${ARTIFACT_DIR}")
source = Path("${source_dir}")
config_path = source / "config/experiments/lab_d_tiny_moe.toml"
data_path = source / "tests/fixtures/algorithm/tiny_pretrain_corpus.txt"
config = tomllib.loads(config_path.read_text(encoding="utf-8"))
request = {
  "schema_version": "klara.moe-run-request.v1",
  "created_at": datetime.now(UTC).isoformat(),
  "source": {"parent_commit": "${AGENTLADDER_PARENT_COMMIT}", "bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}", "deployment": "${source_dir}"},
  "slurm": {"job_id": "${SLURM_JOB_ID}", "node": "${SLURMD_NODENAME}", "partition": "${SLURM_JOB_PARTITION}"},
  "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
  "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
  "seed": config["train"]["seed"], "steps": config["train"]["steps"],
  "precision": config["train"]["precision"], "num_experts": 4, "top_k": 2,
  "scorer_version": "klara.tiny-moe-eval.v1",
  "hardware": {"python": platform.python_version(), "torch": torch.__version__, "cuda_available": torch.cuda.is_available(), "cuda_runtime": torch.version.cuda, "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unavailable"},
  "expected_artifacts": ["dense_control.pt", "tiny_moe.pt", "manifest.json", "lab-d-tiny-moe.json", "lab-d-tiny-moe.md", "training-tests.log", "full-tests.log", "checksums.sha256"]
}
assert request["hardware"]["cuda_available"] is True
(artifact / "run-request.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(request, sort_keys=True))
PY
"${PYTHON_BIN}" -m pytest tests/klara/training/test_moe.py -q | tee "${ARTIFACT_DIR}/training-tests.log"
"${PYTHON_BIN}" -m klara.training.moe_cli \
  --config config/experiments/lab_d_tiny_moe.toml \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}" \
  --json-out "${ARTIFACT_DIR}/lab-d-tiny-moe.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-d-tiny-moe.md" \
  | tee "${ARTIFACT_DIR}/moe.stdout.json"
"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
p=Path("${ARTIFACT_DIR}/lab-d-tiny-moe.json")
r=json.loads(p.read_text(encoding="utf-8"))
assert r["passed"] and all(r["checks"].values()), r["checks"]
print("lab_d_report_gate=PASS")
PY
"${PYTHON_BIN}" -m pytest -q | tee "${ARTIFACT_DIR}/full-tests.log"
(
  cd "${ARTIFACT_DIR}"
  sha256sum dense_control.pt tiny_moe.pt manifest.json lab-d-tiny-moe.json \
    lab-d-tiny-moe.md slurm.json run-request.json moe.stdout.json \
    training-tests.log full-tests.log > checksums.sha256
)
nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "LAB_D_REMOTE_GATE=PASS"
