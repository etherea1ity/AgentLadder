#!/usr/bin/env bash
#SBATCH --job-name=klara-hidden-eval
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/klara-hidden-eval-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/klara-hidden-eval-%j.err
set -euo pipefail
R=/userhome/cs2/u3665453/AgentLadder
D=$R/deployments/ddebedac882d8945b9df1974296ad99794e3ccf76533008eb50ae93d622d0a06
PY=$R/.venv/bin/python
cd "$D"
export PYTHONPATH=$D/src
export PYTHONUNBUFFERED=1
"$PY" -m klara.eval.run_klara_eval --config config/eval/hidden_klara.toml --checkpoint "$R/runs/134160/checkpoint_0002000.pt" --output "$R/results/klara-hidden.json"
