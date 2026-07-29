#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${1:-caption-studio:smoke}"
EXPECTED_VERSION="$(python3 -c 'import json; print(json.load(open("studio.json"))["version"])')"
CONTAINER_NAME="caption-studio-smoke"
VOLUME_NAME="caption-studio-smoke-data"
HOST_PORT="${CAPTION_STUDIO_SMOKE_PORT:-18788}"
TEMP_DIR="$(mktemp -d)"

cleanup() {
  docker rm --force "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

docker run --detach \
  --name "$CONTAINER_NAME" \
  --publish "${HOST_PORT}:8788" \
  --volume "${VOLUME_NAME}:/data" \
  "$IMAGE_NAME" >/dev/null

for _attempt in $(seq 1 60); do
  if curl --fail --silent "http://127.0.0.1:${HOST_PORT}/api/health" >"$TEMP_DIR/health.json"; then
    if python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); assert p["ok"] and p["asr"]["provider"] == "faster-whisper"' "$TEMP_DIR/health.json"; then
      break
    fi
  fi
  sleep 2
done

python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); assert p["ok"], p' "$TEMP_DIR/health.json"
curl --fail --silent "http://127.0.0.1:${HOST_PORT}/api/version" \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["version"] == sys.argv[1] and p["license"] == "Apache-2.0"' "$EXPECTED_VERSION"

docker exec "$CONTAINER_NAME" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=0x17202a:s=640x360:d=2:r=24" \
  -f lavfi -i "sine=frequency=440:duration=2" \
  -c:v mpeg4 -q:v 5 -c:a aac -shortest /tmp/source.mp4
docker cp "$CONTAINER_NAME:/tmp/source.mp4" "$TEMP_DIR/source.mp4"

curl --fail --silent \
  --request POST \
  --data-binary "@$TEMP_DIR/source.mp4" \
  "http://127.0.0.1:${HOST_PORT}/api/media?filename=source.mp4" >"$TEMP_DIR/media.json"
MEDIA_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["media_id"])' "$TEMP_DIR/media.json")"

# The named volume must preserve the upload across a container restart.
docker restart "$CONTAINER_NAME" >/dev/null
for _attempt in $(seq 1 30); do
  curl --fail --silent "http://127.0.0.1:${HOST_PORT}/api/health" >/dev/null && break
  sleep 1
done

python3 - "$MEDIA_ID" "$HOST_PORT" >"$TEMP_DIR/render-request.json" <<'PY'
import json, sys
media_id, port = sys.argv[1:]
print(json.dumps({
    "media_id": media_id,
    "captions": [{"id": "smoke-1", "start": 0.1, "end": 1.8, "text": "Caption Studio Docker"}],
    "global_style": {
        "fontFamily": "Noto Sans CJK KR",
        "fontSize": 34,
        "color": "#ffffff",
        "outlineEnabled": True,
        "outlineColor": "#000000",
        "outlineWidth": 2,
        "backgroundEnabled": True,
        "backgroundColor": "rgba(0,0,0,0.55)",
        "position": "bottom",
        "align": "center",
        "offsetX": 0,
        "offsetY": 0,
    },
}))
PY

curl --fail --silent \
  --request POST \
  --header "Content-Type: application/json" \
  --data-binary "@$TEMP_DIR/render-request.json" \
  "http://127.0.0.1:${HOST_PORT}/api/jobs/render" >"$TEMP_DIR/job.json"
JOB_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job_id"])' "$TEMP_DIR/job.json")"

for _attempt in $(seq 1 90); do
  curl --fail --silent "http://127.0.0.1:${HOST_PORT}/api/jobs/${JOB_ID}" >"$TEMP_DIR/job-status.json"
  STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$TEMP_DIR/job-status.json")"
  if [ "$STATUS" = "complete" ]; then
    break
  fi
  if [ "$STATUS" = "error" ]; then
    python3 -c 'import json,sys; raise SystemExit(json.load(open(sys.argv[1])).get("error"))' "$TEMP_DIR/job-status.json"
  fi
  sleep 1
done

test "$STATUS" = "complete"
curl --fail --silent --output "$TEMP_DIR/captioned.mp4" "http://127.0.0.1:${HOST_PORT}/api/jobs/${JOB_ID}/download"
test -s "$TEMP_DIR/captioned.mp4"
echo "Caption Studio Docker smoke test passed."
