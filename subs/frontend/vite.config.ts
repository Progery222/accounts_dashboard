import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** База URL Django для dev/preview-прокси (без завершающего `/`). */
function subsDevProxyTarget(env: Record<string, string>): string {
  const raw = (env.SUBS_DEV_PROXY_TARGET || env.VITE_DASHBOARD_API_URL || "").trim();
  if (!raw) return "http://127.0.0.1:8000";
  return raw.replace(/\/$/, "");
}

/** Одинаковый прокси для `vite dev` и `vite preview` (HTTPS trycloudflare → /api без mixed content).
 * Долгие POST (съём аудитории через цепочку subs → дашборд) — большие таймауты сокета прокси.
 */
function buildSubsBackendProxy(target: string) {
  const common = {
    target,
    changeOrigin: true,
    /** Цель локально по HTTP — не требовать валидный TLS у апстрима. */
    secure: false,
  } as const;
  return {
    "/api": { ...common, timeout: 3_600_000, proxyTimeout: 3_600_000 },
    "/admin": { ...common, timeout: 120_000, proxyTimeout: 120_000 },
    "/static": { ...common, timeout: 120_000, proxyTimeout: 120_000 },
    "/healthz": { ...common, timeout: 30_000, proxyTimeout: 30_000 },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "");
  const proxyTarget = subsDevProxyTarget(env);
  const subsBackendProxy = buildSubsBackendProxy(proxyTarget);

  return {
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
  };
});
