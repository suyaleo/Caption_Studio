#!/usr/bin/env bash
# Caption Studio verification helper. Run from anywhere inside the repo.
# Usage: verify.sh doctor | suite | ci | cli-export [fmt] | web-export [fmt] | all | cleanup
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SKILL_DIR="$REPO_ROOT/.cursor/skills/verify-caption-studio"
EVIDENCE_ROOT="${CAPTION_STUDIO_VERIFY_EVIDENCE:-/tmp/caption-studio-verify}"
RUN_ID="${CAPTION_STUDIO_VERIFY_RUN:-$(date +%Y%m%d-%H%M%S)}"
EVIDENCE="$EVIDENCE_ROOT/$RUN_ID"
SCRATCH="$EVIDENCE_ROOT/.scratch-$RUN_ID"
mkdir -p "$EVIDENCE"
cd "$REPO_ROOT"

log() { printf '[verify] %s\n' "$*" | tee -a "$EVIDENCE/verify.log"; }
FAILED=()
step() { # step <name> <cmd...> : runs, keeps transcript, records failure (final exit is non-zero)
  local name="$1"; shift
  log "RUN $name: $*"
  if "$@" >"$EVIDENCE/$name.log" 2>&1; then log "PASS $name"; else
    log "FAIL $name (see $EVIDENCE/$name.log)"; tail -c 3000 "$EVIDENCE/$name.log"; FAILED+=("$name"); return 1; fi
}

doctor() {
  local ok=0
  for tool in uv node npm git; do command -v "$tool" >/dev/null || { echo "missing: $tool"; ok=1; }; done
  command -v chromium >/dev/null || command -v google-chrome >/dev/null || echo "warn: no chromium; web-export drive unavailable"
  echo "repo: $REPO_ROOT  branch: $(git branch --show-current)  head: $(git rev-parse --short HEAD)"
  echo "version: $(python3 -c 'import json;print(json.load(open("studio.json"))["version"])')"
  echo "node: $(node -v) (CI pins 22.23.2)  uv: $(uv --version)"
  test -f src/subtitle_automation/static/index.html || { echo "missing packaged static build"; ok=1; }
  test -d web/node_modules || echo "note: web/node_modules absent; suite runs npm ci"
  return $ok
}

suite() { # local mirror of .github/workflows/ci.yml "application" job + pytest
  step uv-sync uv sync --locked || true
  step validate-release uv run python scripts/validate_studio_repo.py --mode release || true
  step python-unittest uv run python -m unittest discover -s tests -v || true
  step python-pytest uv run --with pytest pytest -q tests || true
  step npm-ci bash -c 'cd web && npm ci' || true
  step web-typecheck bash -c 'cd web && npm run typecheck' || true
  step web-vitest bash -c 'cd web && npm test' || true
  step web-build bash -c 'cd web && npm run build' || true
  # Mirrors CI: the rebuilt static must equal what is committed. Commit rebuilt static before running.
  step static-in-sync git diff --stat --exit-code -- src/subtitle_automation/static || true
  step uv-tool-install bash scripts/test_uv_tool_install.sh || true
}

ci_docker() { # CI "docker" job; needs docker daemon access
  step docker-build docker build --build-arg APP_VERSION="$(python3 -c 'import json;print(json.load(open("studio.json"))["version"])')" --build-arg VCS_REF="$(git rev-parse HEAD)" --tag caption-studio:verify . || true
  step docker-user test "$(docker image inspect caption-studio:verify --format '{{.Config.User}}')" = studio || true
  step docker-smoke bash scripts/docker_smoke_test.sh caption-studio:verify || true
}

cli_export() { # real CLI path: demo job -> segment-local -> format-<fmt>
  local fmt="${1:-ass}"
  local cues="$EVIDENCE/demo_cues.json" out="$EVIDENCE/demo.${1:-ass}"
  step cli-segment uv run subtitle-automation segment-local --input examples/demo_input.json --output "$cues" || return 1
  step "cli-format-$fmt" uv run subtitle-automation "format-$fmt" --input "$cues" --output "$out" || return 1
  python3 "$SKILL_DIR/scripts/check_subtitle.py" "$fmt" "$out" | tee "$EVIDENCE/cli-check-$fmt.txt" || return 1
  log "CLI sample: $out"; head -n 10 "$out"
}

web_export() { # real UI path: packaged server + headless chromium clicks the export button
  local fmt="${1:-ass}"
  mkdir -p "$SCRATCH"
  local port; port="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')"
  uv run caption-studio --host 127.0.0.1 --port "$port" --workspace "$SCRATCH/workspace" >"$EVIDENCE/server.log" 2>&1 &
  echo $! >"$SCRATCH/server.pid"
  for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$port/api/health" >"$EVIDENCE/health.json" 2>/dev/null && break; sleep 0.2; done
  test -s "$EVIDENCE/health.json" || { log "server not ready"; cleanup; return 1; }
  local rc=0
  node "$SKILL_DIR/scripts/web_export.mjs" "http://127.0.0.1:$port/" "$fmt" "$EVIDENCE" "$SCRATCH/chrome" || rc=$?
  cleanup
  [ $rc -eq 0 ] || return $rc
  local file; file="$(ls "$EVIDENCE"/web-download/*."$fmt" | head -1)" || return 1
  python3 "$SKILL_DIR/scripts/check_subtitle.py" "$fmt" "$file" | tee "$EVIDENCE/web-check-$fmt.txt" || return 1
  log "web sample: $file"
}

cleanup() { # kills only what this helper started; evidence is kept
  for d in "$EVIDENCE_ROOT"/.scratch-*; do
    [ -d "$d" ] || continue
    if [ -f "$d/server.pid" ]; then kill "$(cat "$d/server.pid")" 2>/dev/null || true; fi
    if [ -f "$d/chrome.pid" ]; then kill "$(cat "$d/chrome.pid")" 2>/dev/null || true; fi
    rm -rf "$d"
  done
}

case "${1:-}" in
  doctor) doctor ;;
  suite) suite ;;
  ci) suite; ci_docker ;;
  cli-export) cli_export "${2:-ass}" || FAILED+=(cli-export) ;;
  web-export) web_export "${2:-ass}" || FAILED+=(web-export) ;;
  all) doctor; suite; cli_export "${2:-ass}" || FAILED+=(cli-export); web_export "${2:-ass}" || FAILED+=(web-export) ;;
  cleanup) cleanup ;;
  *) sed -n 2,3p "$0"; exit 2 ;;
esac
log "evidence: $EVIDENCE"
if [ ${#FAILED[@]} -gt 0 ]; then log "RESULT: FAIL (${FAILED[*]})"; exit 1; fi
log "RESULT: PASS"
