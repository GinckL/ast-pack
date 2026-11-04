import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` proxies the API to a running `ast-pack serve` (default port 7878).
const API = process.env.AST_PACK_API ?? "http://127.0.0.1:7878";

export default defineConfig({
  plugins: [react()],
  base: "/",
  // The highlighter worker lazy-loads grammars, so it must be an ES module.
  worker: { format: "es" },
  build: {
    // The Python package serves this directory (src/ast_pack/web).
    outDir: "../src/ast_pack/web",
    emptyOutDir: true,
    target: "es2020",
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          motion: ["framer-motion"],
          graph: ["d3-force"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": API,
      "/ws": { target: API.replace(/^http/, "ws"), ws: true },
    },
  },
});
