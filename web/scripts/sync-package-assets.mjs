import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(webRoot, "dist");
const destination = resolve(webRoot, "..", "src", "subtitle_automation", "static");

if (!existsSync(join(source, "index.html"))) {
  throw new Error("Vite output is missing. Run the production build first.");
}

rmSync(destination, { recursive: true, force: true });
mkdirSync(destination, { recursive: true });
cpSync(source, destination, { recursive: true });
console.log(`Synced packaged Web assets to ${destination}`);
