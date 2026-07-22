import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  clearScreen: false,
  server: {
    // Prefer 1420; if busy (IPv4 or IPv6), Vite picks the next free port.
    // scripts/dev.mjs starts Vite first and syncs Tauri's devUrl to the
    // actual bound port.
    port: 1420,
    strictPort: false,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    target: "chrome105",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
} as never);
