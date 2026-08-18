#!/usr/bin/env bash
#SBATCH --job-name=klara-corpus
#SBATCH --partition=batch
#SBATCH --gres=gpu:rtx_4080:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=/userhome/cs2/u3665453/AgentLadder/runs/klara-corpus-%j.log
#SBATCH --error=/userhome/cs2/u3665453/AgentLadder/runs/klara-corpus-%j.err
set -euo pipefail
R=/userhome/cs2/u3665453/AgentLadder
PY="$R/.venv/bin/python"
SRC="$R/deployments/ddebedac882d8945b9df1974296ad99794e3ccf76533008eb50ae93d622d0a06"
export HF_HOME="$R/.cache/huggingface"
export PYTHONUNBUFFERED=1
cd "$SRC"
"$PY" scripts/hku/prepare_pretrain_corpus.py --config config/corpus.toml
