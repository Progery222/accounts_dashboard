import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Одинаковый прокси для `vite dev` и `vite preview` (HTTPS trycloudflare → /api без mixed content). */
const subsBackendProxy: Record<string, { target: string; changeOrigin: boolean }> = {
  "/api": { target: "http://127.0.0.1:8010", changeOrigin: true },
  "/admin": { target: "http://127.0.0.1:8010", changeOrigin: true },
  "/static": { target: "http://127.0.0.1:8010", changeOrigin: true },
  "/healthz": { target: "http://127.0.0.1:8010", changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5180,
    strictPort: true,
    // Иначе запросы через Cloudflare Quick Tunnel (Host: *.trycloudflare.com) получают 403 → edge показывает 502.
    allowedHosts: [".trycloudflare.com", ".loca.lt", "localhost", ".localhost", "127.0.0.1"],
    proxy: subsBackendProxy,
  },
  preview: {
    host: true,
    port: 5180,
    strictPort: true,
    allowedHosts: [".trycloudflare.com", ".loca.lt", "localhost", ".localhost", "127.0.0.1"],
    proxy: subsBackendProxy,
  },
});
