#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fetch_pdf() {
  local url="$1"
  local out="$2"
  mkdir -p "$(dirname "$out")"
  echo "Downloading $url"
  curl -L --fail --retry 3 --connect-timeout 20 -o "$out" "$url"
  echo "Saved to $out"
}

fetch_pdf "https://arxiv.org/pdf/2606.09071" "$ROOT_DIR/最相关/REFLECT-Silent-Failure-Attribution/paper.pdf"
fetch_pdf "https://arxiv.org/pdf/2606.09863" "$ROOT_DIR/最相关/False-Success-Silent-Failure/paper.pdf"
fetch_pdf "https://arxiv.org/pdf/2602.02475" "$ROOT_DIR/最相关/AgentRx-Diagnosing-Agent-Failures/paper.pdf"
fetch_pdf "https://arxiv.org/pdf/2602.06443" "$ROOT_DIR/高度相关/TrajAD-Trajectory-Anomaly-Detection/paper.pdf"
fetch_pdf "https://arxiv.org/pdf/2511.08325" "$ROOT_DIR/高度相关/AgentPRM-Process-Reward-Models/paper.pdf"

echo "Done."
