import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend runs at http://localhost:8000. Proxy the two endpoints
// the frontend talks to so the app can use same-origin /health and /chat.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/chat": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
