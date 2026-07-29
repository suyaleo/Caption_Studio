#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew가 필요합니다: https://brew.sh" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  brew install uv
fi

brew install ffmpeg-full
uv venv --python 3.11 "$REPO_ROOT/.venv"
uv pip install --python "$REPO_ROOT/.venv/bin/python" -e "$REPO_ROOT[asr]"
npm --prefix "$REPO_ROOT/web" install

echo "준비 완료: cd '$REPO_ROOT/web' && npm run dev"
