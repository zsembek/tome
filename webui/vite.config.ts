import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // dev proxy to the gateway so that /v1 works without CORS
    proxy: {
      "/v1": "http://localhost:8080",
      "/health": "http://localhost:8080",
      "/docs": "http://localhost:8080",
      "/openapi.json": "http://localhost:8080",
    },
  },
});
