#!/bin/bash
# Деплой навигации account-stats + collapse sidebar (запуск на VPS из /tmp)
set -e
AS=/opt/atome-studio/apps/web/src

mkdir -p "$AS/pages/AccountStats"
cp /tmp/atome-patches/AccountStatsPage.tsx "$AS/pages/AccountStats/AccountStatsPage.tsx"
cp /tmp/atome-patches/AccountStatsPage.module.css "$AS/pages/AccountStats/AccountStatsPage.module.css"
cp /tmp/atome-patches/AnalyticsPage.tsx "$AS/pages/Analytics/AnalyticsPage.tsx"
cp /tmp/atome-patches/Layout.tsx "$AS/components/Layout/Layout.tsx"
grep -q 'sidebarCollapse' "$AS/components/Layout/Layout.module.css" || cat /tmp/atome-patches/Layout.module.css.patch >> "$AS/components/Layout/Layout.module.css"

python3 /tmp/patch_atome_i18n.py

# App.tsx: import + route
grep -q AccountStatsPage "$AS/../App.tsx" 2>/dev/null || grep -q AccountStatsPage /opt/atome-studio/apps/web/src/App.tsx
APP=/opt/atome-studio/apps/web/src/App.tsx
if ! grep -q 'AccountStatsPage' "$APP"; then
  sed -i '/import { AnalyticsPage }/a import { AccountStatsPage } from "./pages/AccountStats/AccountStatsPage";' "$APP"
  sed -i '/path="\/analytics"/a\              <Route path="/account-stats" element={<AccountStatsPage />} />' "$APP"
fi

echo "patched atome-studio web"
