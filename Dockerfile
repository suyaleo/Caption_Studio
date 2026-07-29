# syntax=docker/dockerfile:1.7
FROM node:26-alpine AS web-builder
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ARG APP_VERSION=0.5.1
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Caption Studio" \
      org.opencontainers.image.description="Local-first subtitle editor, transcription, translation and hard-sub renderer" \
      org.opencontainers.image.source="https://github.com/suyaleo/Caption_Studio" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAPTION_STUDIO_HOST=0.0.0.0 \
    CAPTION_STUDIO_PORT=8788 \
    CAPTION_STUDIO_WORKSPACE=/data/workspace \
    CAPTION_STUDIO_STATIC_DIR=/app/web-dist \
    CAPTION_ASR_PROVIDER=faster-whisper \
    CAPTION_ASR_DEVICE=cpu \
    CAPTION_ASR_COMPUTE_TYPE=int8 \
    CAPTION_ASR_DOWNLOAD_ROOT=/data/models \
    CAPTION_TRANSLATION_BASE_URL=http://host.docker.internal:8000/v1 \
    CAPTION_TRANSLATION_API_KEY=local \
    HF_HOME=/data/models/huggingface

WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 studio \
    && useradd --system --uid 10001 --gid studio --home-dir /app studio \
    && mkdir -p /data/workspace /data/models /app/web-dist \
    && chown -R studio:studio /data /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[asr-docker]"

COPY --chown=studio:studio --from=web-builder /build/web/dist/ /app/web-dist/

USER studio
VOLUME ["/data"]
EXPOSE 8788
HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=4 \
  CMD python -c "import json, urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health', timeout=5)); raise SystemExit(0 if p.get('ok') else 1)"

CMD ["python", "-m", "subtitle_automation.web_server"]
