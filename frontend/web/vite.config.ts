import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // three.js (~1 MB, needed on the home page) and the lazy-loaded exceljs/pdfjs/docx
    // renderers are legitimately large; the default 500 kB warning is just noise here.
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\/](three|@react-three|postprocessing|three-stdlib|maath|troika-[^/]+|camera-controls)[\/]/.test(id)) {
            return "vendor-three";
          }
          if (/[\/](react|react-dom|react-router|react-router-dom|@remix-run|scheduler|zustand|@tanstack)[\/]/.test(id)) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
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
