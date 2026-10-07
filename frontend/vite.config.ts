import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The site is served from the root of the custom domain impact.bioconductor.org
// (frontend/public/CNAME), so the base is "/" for dev and production alike.
export default defineConfig({
  base: "/",
  plugins: [react()],
  // duckdb-wasm ships large prebuilt wasm; don't let Vite try to inline/optimize it.
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
  worker: { format: "es" },
});
