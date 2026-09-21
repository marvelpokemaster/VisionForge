/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy so the frontend never hardcodes the API host: it calls
// same-origin "/api/..." and Vite forwards to the FastAPI backend.
const API_TARGET = process.env.VISIONFORGE_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, "")
      }
    }
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
});
