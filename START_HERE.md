# Start Here

Caption Studio is a local-first subtitle editor and rendering application.

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
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
cd web && npm run typecheck && npm test && npm run build
cd .. && python3 scripts/validate_studio_repo.py --mode release
```

See [README.md](./README.md) for product features, runtime providers and release instructions.
