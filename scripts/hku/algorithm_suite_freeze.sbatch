#!/usr/bin/env bash
#SBATCH --job-name=klara-freeze
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/logs/algorithm-suite-freeze-%j.log

set -euo pipefail
readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly PYTHON_BIN="${REMOTE_ROOT}/.venv/bin/python"
readonly ARTIFACT_DIR="${REMOTE_ROOT}/artifacts/algorithm-suite-freeze/job-${SLURM_JOB_ID}"
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
mkdir -p "${ARTIFACT_DIR}"/{lab-a,lab-b,lab-c,lab-e,lab-h}
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

"${PYTHON_BIN}" -m klara.eval.cli gate \
  --fixture tests/fixtures/algorithm/gate1_gold.json \
  --config config/experiments/lab_a_evidence_eval.toml \
  --json-out "${ARTIFACT_DIR}/lab-a/report.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-a/report.md"

"${PYTHON_BIN}" -m klara.training.cli pretrain \
  --config config/experiments/lab_b_tiny_pretrain.toml \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}/lab-b" \
  --json-out "${ARTIFACT_DIR}/lab-b/report.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-b/report.md"

"${PYTHON_BIN}" - <<PY
import hashlib, json
from pathlib import Path
root = Path("${ARTIFACT_DIR}")
source = Path("${source_dir}")
b = json.loads((root / "lab-b/report.json").read_text(encoding="utf-8"))
text = (source / "config/experiments/lab_c_trajectory_distillation.toml").read_text(encoding="utf-8")
text = text.replace(
    '/userhome/cs2/u3665453/AgentLadder/artifacts/lab-b-tiny-pretrain/job-133910/tiny_dense.pt',
    (root / "lab-b/tiny_dense.pt").as_posix(),
).replace(
    'ea885bc2e6cb5aebacb576b85c1c61876a711962842a9e1ac84a1f677895d9f3',
    b["checkpoint"]["sha256"],
)
(root / "lab-c/config.toml").write_text(text, encoding="utf-8")
request = {
    "schema_version": "klara.algorithm-suite-request.v1",
    "source_bundle_sha256": "${AGENTLADDER_SOURCE_BUNDLE_SHA256}",
    "parent_commit": "${AGENTLADDER_PARENT_COMMIT}",
    "slurm_job_id": "${SLURM_JOB_ID}",
    "dense_checkpoint_sha256": b["checkpoint"]["sha256"],
}
(root / "run-request.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
"${PYTHON_BIN}" -m klara.training.distillation_cli \
  --config "${ARTIFACT_DIR}/lab-c/config.toml" \
  --artifact-dir "${ARTIFACT_DIR}/lab-c" \
  --json-out "${ARTIFACT_DIR}/lab-c/report.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-c/report.md"

"${PYTHON_BIN}" -m klara.training.moe_cli \
  --config config/experiments/lab_d_tiny_moe.toml \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}/lab-e" \
  --json-out "${ARTIFACT_DIR}/lab-e/report.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-e/report.md"

"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
root = Path("${ARTIFACT_DIR}")
source = Path("${source_dir}")
c = json.loads((root / "lab-c/report.json").read_text(encoding="utf-8"))
text = (source / "config/experiments/lab_e_fp16_fp4.toml").read_text(encoding="utf-8")
text = text.replace(
    '/userhome/cs2/u3665453/AgentLadder/artifacts/lab-c-trajectory-distillation/job-133913/tiny_distilled.pt',
    (root / "lab-c/tiny_distilled.pt").as_posix(),
).replace(
    '90962b25e5a67bd6978a6ee8408f62563539765dc9f7ee28e51491f9d95d56be',
    c["checkpoint"]["sha256"],
)
(root / "lab-h/config.toml").write_text(text, encoding="utf-8")
request_path = root / "run-request.json"
request = json.loads(request_path.read_text(encoding="utf-8"))
request["distilled_checkpoint_sha256"] = c["checkpoint"]["sha256"]
request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
"${PYTHON_BIN}" -m klara.training.quantization_cli \
  --config "${ARTIFACT_DIR}/lab-h/config.toml" \
  --corpus tests/fixtures/algorithm/tiny_pretrain_corpus.txt \
  --artifact-dir "${ARTIFACT_DIR}/lab-h" \
  --json-out "${ARTIFACT_DIR}/lab-h/report.json" \
  --markdown-out "${ARTIFACT_DIR}/lab-h/report.md"

"${PYTHON_BIN}" -m pytest -q \
  --junitxml="${ARTIFACT_DIR}/full-tests.xml" \
  | tee "${ARTIFACT_DIR}/full-tests.log"
"${PYTHON_BIN}" -m klara.eval.suite \
  --lab-a "${ARTIFACT_DIR}/lab-a/report.json" \
  --lab-b "${ARTIFACT_DIR}/lab-b/report.json" \
  --lab-c "${ARTIFACT_DIR}/lab-c/report.json" \
  --lab-e "${ARTIFACT_DIR}/lab-e/report.json" \
  --lab-h "${ARTIFACT_DIR}/lab-h/report.json" \
  --source-state "${source_dir}/.tmp/hku/source-state.json" \
  --test-results "${ARTIFACT_DIR}/full-tests.xml" \
  --json-out "${ARTIFACT_DIR}/algorithm-suite-freeze.json" \
  --markdown-out "${ARTIFACT_DIR}/algorithm-suite-freeze.md" \
  | tee "${ARTIFACT_DIR}/suite.stdout.json"
"${PYTHON_BIN}" - <<PY
import json
from pathlib import Path
p = Path("${ARTIFACT_DIR}/algorithm-suite-freeze.json")
r = json.loads(p.read_text(encoding="utf-8"))
assert r["passed"] and all(r["checks"].values()), r["checks"]
assert all(r["stage_checks"].values()), r["stage_checks"]
print("algorithm_suite_report_gate=PASS")
PY
(
  cd "${ARTIFACT_DIR}"
  sha256sum \
    lab-a/report.json lab-a/report.md \
    lab-b/report.json lab-b/report.md lab-b/manifest.json lab-b/tiny_dense.pt \
    lab-c/report.json lab-c/report.md lab-c/manifest.json lab-c/tiny_distilled.pt \
    lab-e/report.json lab-e/report.md lab-e/manifest.json lab-e/dense_control.pt lab-e/tiny_moe.pt \
    lab-h/report.json lab-h/report.md lab-h/manifest.json lab-h/tiny_fp16_amp.pt lab-h/tiny_w4a16.pt \
    algorithm-suite-freeze.json algorithm-suite-freeze.md suite.stdout.json \
    slurm.json run-request.json full-tests.log full-tests.xml > checksums.sha256
)
nvidia-smi --query-gpu=name,memory.used,temperature.gpu --format=csv,noheader
echo "ALGORITHM_SUITE_REMOTE_GATE=PASS"
