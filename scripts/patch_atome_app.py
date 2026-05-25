#!/usr/bin/env python3
from pathlib import Path

app = Path("/opt/atome-studio/apps/web/src/App.tsx")
text = app.read_text(encoding="utf-8")
imp = 'import { AccountStatsPage } from "./pages/AccountStats/AccountStatsPage";'
if imp not in text:
    text = text.replace(
        'import { AnalyticsPage } from "./pages/Analytics/AnalyticsPage";',
        'import { AnalyticsPage } from "./pages/Analytics/AnalyticsPage";\n' + imp,
    )
route = '              <Route path="/account-stats" element={<AccountStatsPage />} />'
if "/account-stats" not in text:
    text = text.replace(
        '              <Route path="/analytics" element={<AnalyticsPage />} />',
        '              <Route path="/analytics" element={<AnalyticsPage />} />\n' + route,
    )
app.write_text(text, encoding="utf-8")
print("app ok")
