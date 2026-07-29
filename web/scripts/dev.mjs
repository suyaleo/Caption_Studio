import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");
const python = process.env.CAPTION_STUDIO_PYTHON
  || (existsSync(join(repoRoot, ".venv", "bin", "python")) ? join(repoRoot, ".venv", "bin", "python") : "python3");
const environment = { ...process.env, PYTHONPATH: join(repoRoot, "src") };

const api = spawn(python, ["-m", "subtitle_automation.web_server", "--host", "127.0.0.1", "--port", "8790"], {
  cwd: repoRoot,
  env: environment,
  stdio: "inherit",
});
const vite = spawn(join(webRoot, "node_modules", ".bin", "vite"), ["--host", "127.0.0.1", "--port", "8788"], {
  cwd: webRoot,
  env: environment,
  stdio: "inherit",
});

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  api.kill("SIGTERM");
  vite.kill("SIGTERM");
  setTimeout(() => process.exit(code), 80);
}

api.on("exit", (code, signal) => {
  if (!stopping) {
    console.error(`Caption Studio API stopped (${signal ?? code ?? "unknown"}).`);
    stop(code || 1);
  }
});
vite.on("exit", (code, signal) => {
  if (!stopping) {
    console.error(`Vite stopped (${signal ?? code ?? "unknown"}).`);
    stop(code || 1);
  }
});
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
