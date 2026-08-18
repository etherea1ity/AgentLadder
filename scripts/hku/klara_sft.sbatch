#!/usr/bin/env bash
#SBATCH --job-name=klara-sft
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/klara-sft-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/klara-sft-%j.err
set -euo pipefail
R=/userhome/cs2/u3665453/AgentLadder
D=$R/deployments/ddebedac882d8945b9df1974296ad99794e3ccf76533008eb50ae93d622d0a06
PY=$R/.venv/bin/python
CKPT=${KLARA_PRETRAIN_CHECKPOINT:-$R/runs/134155/checkpoint_final.pt}
RUN_DIR=$R/runs/${SLURM_JOB_ID}
mkdir -p "$RUN_DIR"
export PYTHONPATH=$D/src
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
cd "$D"
"$PY" -m klara.training.sft_grpo_cli sft \
  --config config/experiments/klara_sft.toml \
  --trajectories "${KLARA_TRAIN_TRAJECTORIES:-$R/data/sft/train_2000.jsonl}" \
  --tokenizer-dir "$R/artifacts/klara-moe-pretrain/tokenizer" \
  --artifact-dir "$RUN_DIR" \
  --pretrain-from "$CKPT"
