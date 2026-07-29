import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");
const python = process.env.CAPTION_STUDIO_PYTHON
  || (existsSync(join(repoRoot, ".venv", "bin", "python")) ? join(repoRoot, ".venv", "bin", "python") : "python3");
const child = spawn(
  python,
  ["-m", "subtitle_automation.web_server", "--host", "127.0.0.1", "--port", "8788", "--static-dir", join(webRoot, "dist")],
  {
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: join(repoRoot, "src") },
    stdio: "inherit",
  },
);

child.on("exit", (code) => process.exit(code ?? 0));
process.on("SIGINT", () => child.kill("SIGINT"));
process.on("SIGTERM", () => child.kill("SIGTERM"));
