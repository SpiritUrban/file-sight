/**
 * Start FileSight desktop dev with automatic free-port selection.
 *
 * Vite is started first (strictPort: false → falls back if 1420 is busy,
 * including IPv6-only listeners). The actual bound URL is then passed to
 * Tauri as build.devUrl, and beforeDevCommand is a no-op so Tauri does not
 * launch a second Vite instance.
 */
import { createServer } from "vite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const PREFERRED_PORT = 1420;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(__dirname, "..");

const server = await createServer({
  configFile: path.join(desktopRoot, "vite.config.ts"),
  server: {
    port: PREFERRED_PORT,
    strictPort: false,
  },
});

await server.listen();
server.printUrls();

const localUrl =
  server.resolvedUrls?.local?.[0] ?? server.resolvedUrls?.network?.[0];
if (!localUrl) {
  await server.close();
  throw new Error("Vite started but no local URL was resolved");
}

const devUrl = localUrl.replace(/\/$/, "");
const boundPort = Number(new URL(devUrl).port || PREFERRED_PORT);
if (boundPort !== PREFERRED_PORT) {
  console.log(
    `[filesight] port ${PREFERRED_PORT} is busy → using ${devUrl}`,
  );
} else {
  console.log(`[filesight] Vite ready at ${devUrl}`);
}

const configPath = path.join(
  os.tmpdir(),
  `filesight-tauri-dev-${process.pid}.json`,
);
// Vite is already running; keep beforeDevCommand as a cheap no-op so Tauri
// does not start a second dev server on a conflicting port.
fs.writeFileSync(
  configPath,
  JSON.stringify({
    build: {
      devUrl,
      beforeDevCommand: 'node -e "process.exit(0)"',
    },
  }),
  "utf8",
);

const tauriCli = path.join(
  desktopRoot,
  "node_modules",
  "@tauri-apps",
  "cli",
  "tauri.js",
);

const child = spawn(
  process.execPath,
  [tauriCli, "dev", "--config", configPath],
  {
    cwd: desktopRoot,
    stdio: "inherit",
    env: process.env,
  },
);

let cleaning = false;
async function cleanup(code = 0) {
  if (cleaning) return;
  cleaning = true;
  try {
    fs.unlinkSync(configPath);
  } catch {
    // ignore
  }
  try {
    await server.close();
  } catch {
    // ignore
  }
  process.exit(code);
}

child.on("exit", (code, signal) => {
  if (signal) {
    cleanup(1);
    return;
  }
  cleanup(code ?? 1);
});

child.on("error", (err) => {
  console.error(err);
  cleanup(1);
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    try {
      child.kill(sig);
    } catch {
      cleanup(1);
    }
  });
}
