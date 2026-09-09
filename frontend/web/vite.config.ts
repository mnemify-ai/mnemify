import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    proxy: {
      "/api": {
        target: "http://localhost:8783",
        changeOrigin: true,
        // SSE: never buffer the event stream.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes, req) => {
            if (req.url?.includes("/harvest/stream")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
});
