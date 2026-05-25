#!/usr/bin/env python3
"""Добавить nav_account_stats и подписи сайдбара в i18n."""
from pathlib import Path

path = Path("/opt/atome-studio/apps/web/src/i18n/index.ts")
text = path.read_text(encoding="utf-8")

pairs = [
    (
        '    nav_analytics: "◈ Аналитика",',
        '    nav_analytics: "◈ Аналитика",\n    nav_account_stats: "◇ Аналитика аккаунтов",\n    nav_hide_sidebar: "Скрыть меню",\n    nav_show_sidebar: "Показать меню",',
    ),
    (
        '    nav_analytics: "◈ Analytics",',
        '    nav_analytics: "◈ Analytics",\n    nav_account_stats: "◇ Account analytics",\n    nav_hide_sidebar: "Hide sidebar",\n    nav_show_sidebar: "Show sidebar",',
    ),
    (
        '    nav_analytics: "◈ 分析",',
        '    nav_analytics: "◈ 分析",\n    nav_account_stats: "◇ 账户分析",\n    nav_hide_sidebar: "隐藏菜单",\n    nav_show_sidebar: "显示菜单",',
    ),
    (
        '    nav_analytics: "◈ Analítica",',
        '    nav_analytics: "◈ Analítica",\n    nav_account_stats: "◇ Analítica de cuentas",\n    nav_hide_sidebar: "Ocultar menú",\n    nav_show_sidebar: "Mostrar menú",',
    ),
]

for old, new in pairs:
    if new.split("\n")[1] not in text:
        if old not in text:
            raise SystemExit(f"missing: {old[:40]}")
        text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("i18n ok")
