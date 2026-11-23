import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const api = env.VITE_API_TARGET || "http://127.0.0.1:8080";
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
    server: {
      host: "127.0.0.1",
      proxy: { "/api": { target: api, changeOrigin: false } },
    },
    build: {
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks: (id: string) => {
            if (id.includes("node_modules/maplibre-gl")) return "maplibre";
            if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "echarts";
            return undefined;
          },
        },
      },
    },
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
