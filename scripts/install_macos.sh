#!/usr/bin/env bash
set -euo pipefail

RELEASE_REF="${CAPTION_STUDIO_RELEASE_REF:-v0.5.1}"
PACKAGE="caption-studio[asr-macos] @ git+https://github.com/suyaleo/Caption_Studio.git@${RELEASE_REF}"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew가 필요합니다: https://brew.sh" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  brew install uv
fi
FFMPEG_FULL_PREFIX="$(brew --prefix ffmpeg-full 2>/dev/null || true)"
if [[ -z "$FFMPEG_FULL_PREFIX" ]] \
  || ! "$FFMPEG_FULL_PREFIX/bin/ffmpeg" -hide_banner -filters 2>/dev/null | grep ' subtitles ' >/dev/null; then
  brew install ffmpeg-full
fi

uv tool install --force --python 3.11 "$PACKAGE"

echo "설치 완료: caption-studio"
echo "삭제: uv tool uninstall caption-studio"
