# Handoff

## Objective

Deploy Caption Studio on the Ubuntu development and deployment host with Studio-specific Grok or OpenAI Codex device OAuth for caption translation.

## Implemented

- Replaced the host OpenAI-compatible oMLX dependency with provider selection: Grok or Codex.
- Translation invokes only the installed provider CLI in a restricted, non-interactive path:
  - Grok: no plan, no subagents, no web search.
  - Codex: ephemeral, read-only, no repository rules.
- Each provider receives an isolated credential home under the Caption Studio data mount. The container never reads or mounts the Ubuntu user's ~/.grok or ~/.codex.
- Added Tailnet-safe compose defaults: 127.0.0.1:8768, /srv/leostudio/data/caption-studio, and caller UID/GID.
- Added a Caption Studio-only Ubuntu self-hosted GitHub Actions runner with the caption-studio label.
- CI now requires that self-hosted runner.

## Verification completed

- Python unit suite: 35 passed, 1 skipped.
- Web type check, unit tests, and production build: passed.
- Docker image: built successfully; bundled Codex 0.151.0, Grok 1.0.13, and Python 3.11 executed.
- Docker persistent upload and hard-sub render smoke test: passed.

## Deployment sequence

1. Commit this branch, open a PR, and wait for the Ubuntu self-hosted CI result.
2. Merge only after CI passes; fast-forward /srv/leostudio/apps/caption-studio to merged main.
3. Create /srv/leostudio/config/caption-studio/compose.env from .env.example using port 8768, data directory /srv/leostudio/data/caption-studio, and the leo UID/GID.
4. Start with docker compose using that env file.
5. Add only Tailscale Serve on 8768 after loopback health succeeds.
6. Use the app's production panel to select Grok or Codex and complete a separate device login for this Studio.
7. Run a user-approved translation test before calling OAuth functional verification complete.
8. Add or update the Hub Studio card only after the Tailnet endpoint is healthy.

## Constraints

- Do not install Hermes Agent.
- Do not copy private Model Studio implementation into this public repository.
- Do not add an external token broker, shared host credential mount, public ingress, or Tailscale Funnel.
- Do not commit device codes, tokens, auth files, or generated media.
