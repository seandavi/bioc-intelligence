import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves a project site under /<repo>/. Use that as the base in
// production so asset + mart URLs resolve; dev stays at root.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/bioc-intelligence/" : "/",
  plugins: [react()],
  // duckdb-wasm ships large prebuilt wasm; don't let Vite try to inline/optimize it.
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
  worker: { format: "es" },
}));
