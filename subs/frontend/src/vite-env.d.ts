/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_DASHBOARD_API_URL: string;
  readonly VITE_DASHBOARD_APP_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
