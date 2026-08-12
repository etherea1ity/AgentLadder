#!/usr/bin/env bash
#SBATCH --job-name=klara-lab-e
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/logs/lab-e-%j.log

set -euo pipefail
readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly ARTIFACT_DIR="${REMOTE_ROOT}/artifacts/lab-e-fp16-fp4/job-${SLURM_JOB_ID}"
readonly BASE_CHECKPOINT="${REMOTE_ROOT}/artifacts/lab-c-trajectory-distillation/job-133913/tiny_distilled.pt"
readonly BASE_SHA256="90962b25e5a67bd6978a6ee8408f62563539765dc9f7ee28e51491f9d95d56be"
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
[[ -f "${BASE_CHECKPOINT}" ]] || { echo "Missing frozen distilled checkpoint." >&2; exit 4; }
[[ "$(sha256sum "${BASE_CHECKPOINT}" | awk '{print $1}')" == "${BASE_SHA256}" ]] \
  || { echo "Frozen distilled checkpoint hash mismatch." >&2; exit 4; }
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
config_path = source / "config/experiments/lab_e_fp16_fp4.toml"
data_path = source / "tests/fixtures/algorithm/tiny_pretrain_corpus.txt"
manifest_path = source / "tests/fixtures/algorithm/lab_c_public_teacher_manifest.json"
config = tomllib.loads(config_path.read_text(encoding="utf-8"))
request = {
  "schema_version": "klara.quantization-run-request.v1",
  "created_at": datetime.now(UTC).isoformat(),
  "source": {"parent_commit": "${AGENTLADDER_PARENT_COMMIT}", "bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}", "deployment": "${source_dir}"},
  "slurm": {"job_id": "${SLURM_JOB_ID}", "node": "${SLURMD_NODENAME}", "partition": "${SLURM_JOB_PARTITION}"},
  "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
  "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
  "teacher_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
  "base_checkpoint": "${BASE_CHECKPOINT}",
  "base_checkpoint_sha256": "${BASE_SHA256}",
  "fp16": {"seed": config["fp16_train"]["seed"], "steps": config["fp16_train"]["steps"], "precision": config["fp16_train"]["precision"]},
  "fp4": {"format_version": config["fp4"]["format_version"], "block_size": config["fp4"]["block_size"], "activation_precision": config["fp4"]["activation_precision"], "compute_mode": config["fp4"]["compute_mode"]},
  "scorer_version": "klara.fp16-fp4-eval.v1",
  "hardware": {"python": platform.python_version(), "torch": torch.__version__, "cuda_available": torch.cuda.is_available(), "cuda_runtime": torch.version.cuda, "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unavailable"},
  "expected_artifacts": ["tiny_fp16_amp.pt", "tiny_w4a16.pt", "manifest.json", "lab-e-fp16-fp4.json", "lab-e-fp16-fp4.md", "training-tests.log", "full-tests.log", "checksums.sha256"]
}
assert request["hardware"]["cuda_available"] is True
assert request["teacher_manifest_sha256"] == config["teacher_manifest"]["sha256"]
(artifact / "run-request.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(request, sort_keys=True))
PY
"${PYTHON_BIN}" -m pytest \
  tests/klara/training/test_quantization.py \
  tests/klara/training/test_distillation.py -q \
  | tee "${ARTIFACT_DIR}/training-tests.log"
"${PYTHON_BIN}" -m klara.training.quantization_cli \
  --config config/experiments/lab_e_fp16_fp4.toml \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}" \
  --json-out "${ARTIFACT_DIR}/lab-e-fp16-fp4.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-e-fp16-fp4.md" \
  | tee "${ARTIFACT_DIR}/quantization.stdout.json"
"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
p = Path("${ARTIFACT_DIR}/lab-e-fp16-fp4.json")
r = json.loads(p.read_text(encoding="utf-8"))
assert r["passed"] and all(r["checks"].values()), r["checks"]
assert r["fp4"]["native_fp4_compute"] is False
assert r["fp4"]["compute_mode"] == "dequantized_fp4_weight_matmul"
print("lab_e_report_gate=PASS")
PY
"${PYTHON_BIN}" -m pytest -q | tee "${ARTIFACT_DIR}/full-tests.log"
(
  cd "${ARTIFACT_DIR}"
  sha256sum tiny_fp16_amp.pt tiny_w4a16.pt manifest.json lab-e-fp16-fp4.json \
    lab-e-fp16-fp4.md slurm.json run-request.json quantization.stdout.json \
    training-tests.log full-tests.log > checksums.sha256
)
nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "LAB_E_REMOTE_GATE=PASS"
