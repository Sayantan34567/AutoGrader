#!/usr/bin/env bash
# One-shot setup for Ubuntu (lab PC or WSL2 Ubuntu on Windows 11).
#   ./setup_ubuntu.sh                      # everything, model from rules.json
#   ./setup_ubuntu.sh --no-ollama          # skip the local LLM (the agent still works, heuristic readability)
#   ./setup_ubuntu.sh --model llama3.1:8b  # choose the model to pull
# Needs sudo for apt and for the Ollama installer. Safe to run twice.
set -euo pipefail
cd "$(dirname "$0")"

WITH_OLLAMA=1
MODEL=$(python3 -c "import json;print(json.load(open('rules.json'))['llm']['model'])" 2>/dev/null || echo "llama3.2:3b")
while [ $# -gt 0 ]; do
  case "$1" in
    --no-ollama) WITH_OLLAMA=0 ;;
    --model) MODEL="$2"; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
  shift
done

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> 1/5 system packages (gcc, valgrind, cppcheck, python)"
$SUDO apt-get update -y
$SUDO apt-get install -y build-essential valgrind cppcheck python3 python3-pip python3-venv curl git

echo "==> 2/5 Python virtual environment (.venv) and requirements.txt"
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ "$WITH_OLLAMA" -eq 1 ]; then
  echo "==> 3/5 Ollama"
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  if ! curl -fs http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "    starting 'ollama serve' in the background (log: /tmp/ollama.log)"
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    for _ in $(seq 1 30); do curl -fs http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
  fi
  echo "==> 4/5 pulling model $MODEL (first time only, a few GB)"
  ollama pull "$MODEL"
else
  echo "==> 3/5 and 4/5 skipped (--no-ollama)"
fi

echo "==> 5/5 checks"
python check_rules.py $([ "$WITH_OLLAMA" -eq 1 ] && echo --ollama)
python coordinator.py samples/add_good.c --out /tmp/autograder_selftest $([ "$WITH_OLLAMA" -eq 0 ] && echo --no-llm)

cat <<MSG

Done. Next time, in this folder:
  source .venv/bin/activate
  streamlit run main.py            # web UI on http://localhost:8501
  python coordinator.py submissions/add.c   # command line
  python test_coordinator.py       # self-tests
If you used a different model than rules.json names, set "llm.model" in rules.json to "$MODEL".
MSG
