#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
SERVER_PID=""
EXPECTED_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO_ROOT/studio.json")"

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

uv build --wheel --out-dir "$TEMP_ROOT/dist" "$REPO_ROOT"
WHEEL="$(find "$TEMP_ROOT/dist" -maxdepth 1 -name '*.whl' -print -quit)"
test -n "$WHEEL"

export UV_TOOL_DIR="$TEMP_ROOT/tools"
export UV_TOOL_BIN_DIR="$TEMP_ROOT/bin"
uv tool install --python 3.11 "$WHEEL"

"$UV_TOOL_BIN_DIR/caption-studio" --version | grep -F "Caption Studio $EXPECTED_VERSION"

PORT="$(python3 - <<'PY'
import socket
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
)"

CAPTION_STUDIO_WORKSPACE="$TEMP_ROOT/workspace" \
  "$UV_TOOL_BIN_DIR/caption-studio" --host 127.0.0.1 --port "$PORT" \
  >"$TEMP_ROOT/server.log" 2>&1 &
SERVER_PID="$!"

for _ in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:${PORT}/" >"$TEMP_ROOT/index.html"; then
    break
  fi
  sleep 0.2
done

grep -F '<div id="root"></div>' "$TEMP_ROOT/index.html"
curl --fail --silent "http://127.0.0.1:${PORT}/api/version" \
  | python3 -c 'import json,sys; assert json.load(sys.stdin)["version"] == sys.argv[1]' "$EXPECTED_VERSION"
test -d "$TEMP_ROOT/workspace"

echo "uv tool isolated install smoke test: PASS"
