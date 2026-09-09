import { defineConfig } from "vitest/config";

// Pure-logic unit tests only (no DOM): rate smoothing, ETA math, the SSE
// reducer. Run with `npm test`.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
