# Start Here

Caption Studio is a local-first subtitle editor and rendering application.

## Isolated macOS installation

```bash
brew install uv ffmpeg-full
uv tool install --python 3.11 \
  "caption-studio[asr-macos] @ git+https://github.com/suyaleo/Caption_Studio.git@v0.5.1"
caption-studio
```

`uv tool` keeps Caption Studio and MLX in a dedicated environment without changing the system Python.

## Development

```bash
bash scripts/bootstrap_macos.sh
cd web
npm run dev
```

Open `http://127.0.0.1:8788`.

## Docker

```bash
docker compose up --build
```

The Docker service also listens on `http://127.0.0.1:8788` and stores working data beneath `/data`.

## Verification

```bash
uv sync --locked --extra asr-macos
uv run python -m unittest discover -s tests
cd web && npm run typecheck && npm test && npm run build
cd .. && uv run python scripts/validate_studio_repo.py --mode release
bash scripts/test_uv_tool_install.sh
```

See [README.md](./README.md) for product features, runtime providers and release instructions.
