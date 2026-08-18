#!/usr/bin/env bash
#SBATCH --job-name=qwen-eval
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/qwen-eval-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/qwen-eval-%j.err
set -euo pipefail
R=/userhome/cs2/u3665453/AgentLadder
D=$R/deployments/ddebedac882d8945b9df1974296ad99794e3ccf76533008eb50ae93d622d0a06
PY=$R/.venv/bin/python
cd "$D"
export PYTHONPATH=$D/src
export PYTHONUNBUFFERED=1
export HF_HOME=$R/.cache/huggingface
MODE=${QWEN_EVAL_MODE:-nofinetune}
if [ "$MODE" = "qlora" ]; then
  "$PY" -m klara.qwen.no_finetune_baseline run \
    --eval-config config/eval/klara_dev.toml \
    --model Qwen/Qwen2.5-1.5B-Instruct \
    --adapter "$R/artifacts/qwen-qlora-sft/job-134195" \
    --output "$R/results/qwen-qlora-dev.json"
else
  "$PY" -m klara.qwen.no_finetune_baseline run \
    --eval-config config/eval/klara_dev.toml \
    --model Qwen/Qwen2.5-1.5B-Instruct \
    --output "$R/results/qwen-nofinetune-dev.json"
fi
