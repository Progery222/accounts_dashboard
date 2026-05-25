import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useT } from "../../i18n";
import { useAuthStore } from "../../stores/auth";
import { useAutonomyStore } from "../../stores/autonomy";
import { useVhaStore } from "../../stores/vha";
import { SystemBanner } from "../SystemBanner";
import { useFarmStore } from "../../stores/farm";
import { type Lang, useLangStore } from "../../stores/lang";
import { useMetricsStore } from "../../stores/metrics";

import styles from "./Layout.module.css";

const LANGS: { code: Lang; label: string }[] = [
  { code: "ru", label: "RU" },
  { code: "en", label: "EN" },
  { code: "zh", label: "中" },
  { code: "es", label: "ES" },
];

export function Layout() {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const setLang = useLangStore((s) => s.setLang);
  const role = useAuthStore((s) => s.role);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  // biome-ignore lint/correctness/useExhaustiveDependencies: pathname is the trigger
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const demoMode = useMetricsStore((s) => s.demoMode);
  const enableDemo = useMetricsStore((s) => s.enableDemo);
  const disableDemo = useMetricsStore((s) => s.disableDemo);

  const phones = useFarmStore((s) => s.phones);
  const queue = useFarmStore((s) => s.queue);
  const activeJobs = useFarmStore((s) => s.activeJobs);
  const wsConnected = useFarmStore((s) => s.wsConnected);
  const connectWs = useFarmStore((s) => s.connectWs);
  const fetchPhones = useFarmStore((s) => s.fetchPhones);
  const fetchQueue = useFarmStore((s) => s.fetchQueue);
  const autonomyStatus = useVhaStore((s) => s.autonomyStatus);
  const fetchAutonomy = useVhaStore((s) => s.fetchAutonomy);
  const [autonomyHelpOpen, setAutonomyHelpOpen] = useState(false);

  useEffect(() => {
    fetchPhones();
    fetchQueue();
    connectWs();
    fetchAutonomy();
    const id = setInterval(() => {
      fetchPhones();
      fetchQueue();
    }, 60_000);
    const aid = setInterval(fetchAutonomy, 60_000);
    return () => {
      clearInterval(id);
      clearInterval(aid);
    };
  }, [fetchPhones, fetchQueue, connectWs, fetchAutonomy]);

  const phonesOnline = phones.filter((p) => p.status === "active").length;
  const queueActive = queue.filter(
    (q) => q.status === "scheduled" || q.status === "in_progress"
  ).length;
  const generatingNow = activeJobs.filter((j) => j.status === "running").length;

  const sessionsList = useAutonomyStore((s) => s.sessionsList);
  const anomalies = useAutonomyStore((s) => s.anomalies);
  const activeSessionsCount = sessionsList.filter(
    (s) => s.state !== "idle" && s.state !== "terminated"
  ).length;
  const hourAgo = Date.now() - 60 * 60 * 1000;
  const criticalAnomaliesCount = anomalies.filter(
    (a) =>
      (a.severity === "high" || a.severity === "critical") &&
      new Date(a.ts).getTime() > hourAgo &&
      !a.resolved
  ).length;

  const primaryBadge =
    criticalAnomaliesCount > 0
      ? criticalAnomaliesCount
      : queueActive > 0
        ? queueActive
        : phones.length > 0
          ? phonesOnline
          : null;

  const NAV_ITEMS = [
    { path: "/", label: "🌐 Galaxy", badge: null },
    { path: "/dashboard", label: "Dashboard", badge: primaryBadge },
    { path: "/accounts", label: t("nav_accounts"), badge: null },
    ...(role !== "viewer"
      ? [
          {
            path: "/generate",
            label: t("nav_generate"),
            badge: generatingNow > 0 ? generatingNow : null,
          },
        ]
      : []),
    { path: "/videos", label: t("nav_videos"), badge: null },
    { path: "/analytics", label: t("nav_analytics"), badge: null },
    { path: "/account-stats", label: t("nav_account_stats"), badge: null },
    ...(role === "super_admin" ? [{ path: "/clients", label: t("nav_clients"), badge: null }] : []),
    { path: "/settings", label: t("nav_settings"), badge: null },
  ];

  void activeSessionsCount;

  return (
    <div className={`${styles.root} ${sidebarCollapsed ? styles.rootCollapsed : ""}`}>
      <button
        type="button"
        className={styles.hamburger}
        onClick={() => {
          setSidebarCollapsed(false);
          setSidebarOpen(true);
        }}
      >
        &#9776;
      </button>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: overlay dismiss */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: overlay dismiss */}
      <div
        className={`${styles.overlay} ${sidebarOpen ? styles.overlayVisible : ""}`}
        onClick={() => setSidebarOpen(false)}
      />
      {sidebarCollapsed && (
        <button
          type="button"
          className={styles.sidebarExpand}
          onClick={() => setSidebarCollapsed(false)}
          title={t("nav_show_sidebar")}
          aria-label={t("nav_show_sidebar")}
        >
          &gt;
        </button>
      )}
      <nav
        className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ""} ${sidebarCollapsed ? styles.sidebarCollapsed : ""}`}
      >
        <div className={styles.sidebarHead}>
          <Link to="/" className={styles.logo}>
            {t("logo")}
          </Link>
          <button
            type="button"
            className={styles.sidebarCollapse}
            onClick={() => setSidebarCollapsed(true)}
            title={t("nav_hide_sidebar")}
            aria-label={t("nav_hide_sidebar")}
          >
            &lt;
          </button>
        </div>

        <div className={styles.nav}>
          {NAV_ITEMS.map(({ path, label, badge }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) => `${styles.link} ${isActive ? styles.linkActive : ""}`}
            >
              <span>{label}</span>
              {badge !== null && badge !== undefined && (
                <span className={styles.navBadge}>{badge}</span>
              )}
            </NavLink>
          ))}
        </div>

        <div className={styles.wsStatus}>
          <span
            className={styles.wsDot}
            style={{
              background: wsConnected ? "#22c55e" : "#6b7280",
              boxShadow: wsConnected ? "0 0 6px #22c55e" : "none",
            }}
          />
          <span className={styles.wsLabel}>{wsConnected ? "live" : "offline"}</span>
        </div>

        {autonomyStatus && (
          <button
            type="button"
            onClick={() => setAutonomyHelpOpen(true)}
            title={`running_loop=${autonomyStatus.running_loop ? "Yes" : "No"} · enabled_serials=[${(autonomyStatus.enabled_serials ?? []).join(", ")}]`}
            style={{
              margin: "8px 12px",
              padding: "6px 10px",
              background: "transparent",
              border: `1px solid ${autonomyStatus.enabled ? "#22c55e" : "#6b7280"}`,
              borderRadius: 6,
              color: autonomyStatus.enabled ? "#22c55e" : "#9aa",
              fontSize: 11,
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            🤖 Авто: {autonomyStatus.enabled ? "ON" : "OFF"}
            {autonomyStatus.interval_sec
              ? ` · ${Math.round(autonomyStatus.interval_sec / 60)}min`
              : ""}
          </button>
        )}

        <div className={styles.spacer} />

        <button
          className={`${styles.demoBtn} ${demoMode ? styles.demoBtnActive : ""}`}
          onClick={() => (demoMode ? disableDemo() : enableDemo())}
        >
          {demoMode ? "✕ DEMO" : "DEMO"}
        </button>

        <div className={styles.langSwitcher}>
          {LANGS.map(({ code, label }) => (
            <button
              key={code}
              className={`${styles.langBtn} ${lang === code ? styles.langBtnActive : ""}`}
              onClick={() => setLang(code)}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      <main className={styles.content}>
        <SystemBanner />
        <Outlet />
      </main>

      {autonomyHelpOpen && (
        // biome-ignore lint/a11y/useKeyWithClickEvents: backdrop
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop
        <div
          onClick={() => setAutonomyHelpOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.6)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {/* biome-ignore lint/a11y/useKeyWithClickEvents: inner */}
          {/* biome-ignore lint/a11y/noStaticElementInteractions: inner */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: 560,
              padding: 24,
              background: "#0e1019",
              border: "1px solid #2a2f44",
              borderRadius: 8,
              color: "#dde",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            <h3 style={{ margin: "0 0 12px", color: "#fff" }}>Autonomy loop control</h3>
            <p>
              Автоматическое включение/выключение через UI <em>не реализовано</em> (backend
              возвращает 501). Чтобы включить:
            </p>
            <pre
              style={{
                background: "#181a25",
                padding: 10,
                borderRadius: 4,
                fontSize: 11,
                overflowX: "auto",
              }}
            >{`ssh root@91.84.98.58
systemctl edit atome-farm.service
# добавь:
[Service]
Environment=VHA_BRAIN_ENABLED=1

systemctl daemon-reload
systemctl restart atome-farm`}</pre>
            <p style={{ marginTop: 12, fontSize: 12, color: "#aab" }}>
              Текущее состояние: enabled={String(autonomyStatus?.enabled)} ·
              running_loop={String(autonomyStatus?.running_loop)} ·
              interval={autonomyStatus?.interval_sec}s
            </p>
            <button
              type="button"
              onClick={() => setAutonomyHelpOpen(false)}
              style={{
                marginTop: 12,
                padding: "6px 14px",
                background: "#1e40af",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
