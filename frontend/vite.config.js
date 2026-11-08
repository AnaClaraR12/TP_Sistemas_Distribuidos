import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento (`npm run dev`), /api é encaminhado ao gateway em :8080.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
      "/.well-known": "http://localhost:8080",
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/__tests__/setup.js",
  },
});
