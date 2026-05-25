import type { MetricsHistoryPoint, MetricsHistoryResponse } from "@atome/shared";
import { useEffect, useState } from "react";
import { Leaderboard } from "../../components/Leaderboard";
import { type ChartSeries, MetricChart } from "../../components/MetricChart";
import { PublishAnalytics } from "../../components/PublishAnalytics";
import { useT } from "../../i18n";
import { apiFetch } from "../../lib/api";
import { useAnalyticsExtraStore } from "../../stores/analyticsExtra";
import { useMetricsStore } from "../../stores/metrics";
import styles from "./AnalyticsPage.module.css";

type Period = "7d" | "14d" | "30d";

const PERIOD_LABELS: Record<Period, string> = {
  "7d": "7 days",
  "14d": "14 days",
  "30d": "30 days",
};

async function fetchHistory(period: Period): Promise<MetricsHistoryResponse> {
  try {
    const res = await apiFetch(`/api/metrics/history?period=${period}&resolution=1h`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as Partial<MetricsHistoryResponse>;
    if (!Array.isArray(data.points)) {
      return { period, resolution: "1h", points: [] };
    }
    return {
      period: data.period ?? period,
      resolution: data.resolution ?? "1h",
      points: data.points,
    };
  } catch (e: any) {
    console.warn("fetchHistory failed:", e);
    return { period, resolution: "1h", points: [] };
  }
}

function generateDemoHistory(period: Period): MetricsHistoryPoint[] {
  const days = period === "7d" ? 7 : period === "14d" ? 14 : 30;
  const now = Date.now();
  const points: MetricsHistoryPoint[] = [];
  for (let i = days; i >= 0; i--) {
    const ts = now - i * 86_400_000;
    const dow = new Date(ts).getDay();
    const isWeekend = dow === 0 || dow === 6;
    const progress = (days - i) / days;
    const r = (d: number) => (Math.random() - 0.5) * 2 * d;
    const videos = Math.max(0, Math.round(18 + progress * 32 + (isWeekend ? -4 : 0) + r(5)));
    const costPer = 0.28 + progress * 0.07 + r(0.03);
    points.push({
      ts,
      videos,
      revenue: +(videos * 1.25 + r(3)).toFixed(2),
      cost: +(videos * costPer + r(1)).toFixed(2),
      accounts_active: Math.max(1, Math.round(14 + progress * 9 + r(2))),
      jobs_completed: Math.max(0, Math.round(2 + progress * 6 + r(2))),
    });
  }
  return points;
}

export function AnalyticsPage() {
  const t = useT();
  const kpis = useMetricsStore((s) => s.kpis);
  const fetchKPIs = useMetricsStore((s) => s.fetchKPIs);
  const demoMode = useMetricsStore((s) => s.demoMode);

  const perfKpis = useAnalyticsExtraStore((s) => s.kpis);
  const accountStats = useAnalyticsExtraStore((s) => s.accountStats);
  const topVideos = useAnalyticsExtraStore((s) => s.topVideos);
  const trafficSources = useAnalyticsExtraStore((s) => s.trafficSources);
  const conversionHistory = useAnalyticsExtraStore((s) => s.conversionHistory);
  const generationStats = useAnalyticsExtraStore((s) => s.generationStats);
  const costReport = useAnalyticsExtraStore((s) => s.costReport);
  const fetchGenerationStats = useAnalyticsExtraStore((s) => s.fetchGenerationStats);
  const fetchCostStats = useAnalyticsExtraStore((s) => s.fetchCostStats);
  const generateDemo = useAnalyticsExtraStore((s) => s.generateDemo);

  const [period, setPeriod] = useState<Period>("30d");
  const [history, setHistory] = useState<MetricsHistoryPoint[]>([]);

  useEffect(() => {
    fetchKPIs();
    fetchGenerationStats();
    fetchCostStats();
    const id = setInterval(() => {
      fetchGenerationStats();
      fetchCostStats();
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (demoMode) {
      setHistory(generateDemoHistory(period));
      generateDemo(period);
    } else {
      fetchHistory(period).then((r) => setHistory(r.points));
    }
  }, [period, demoMode, generateDemo]);

  const labels = history.map((p) =>
    new Date(p.ts).toLocaleDateString("en", { month: "short", day: "numeric" })
  );

  const videosSeries: ChartSeries[] = [
    { name: "Videos", data: history.map((p) => p.videos), color: "var(--accent-cyan)" },
  ];
  const revSeries: ChartSeries[] = [
    { name: "Revenue", data: history.map((p) => p.revenue), color: "var(--color-success)" },
    { name: "Cost", data: history.map((p) => p.cost), color: "var(--accent-red)" },
  ];
  const accountsSeries: ChartSeries[] = [
    {
      name: "Active accounts",
      data: history.map((p) => p.accounts_active),
      color: "var(--accent-amber)",
    },
  ];
  const jobsSeries: ChartSeries[] = [
    {
      name: "Jobs completed",
      data: history.map((p) => p.jobs_completed),
      color: "var(--accent-purple)",
    },
  ];

  const nicheSeries: ChartSeries[] = [
    { name: "Sport", data: [30], color: "var(--accent-cyan)" },
    { name: "Content", data: [25], color: "var(--accent-pink)" },
    { name: "Music", data: [20], color: "#00c8dc" },
    { name: "News", data: [15], color: "var(--accent-amber)" },
    { name: "Other", data: [10], color: "var(--color-success)" },
  ];

  const kpiCards = [
    { label: "Videos Today", value: kpis.videos_today, fmt: (v: number) => String(v) },
    {
      label: "Cost / Video",
      value: kpis.cost_per_video,
      fmt: (v: number) => `$${v.toFixed(2)}`,
    },
    {
      label: "Publish Rate",
      value: Math.round(asPercent(kpis.publish_rate)),
      fmt: (v: number) => `${v}%`,
    },
    { label: "Active Accounts", value: kpis.active_accounts, fmt: (v: number) => String(v) },
    {
      label: "Uptime",
      value: kpis.uptime_percent,
      fmt: (v: number) => `${v}%`,
    },
  ];

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <h1 className={styles.title}>Analytics</h1>
      </div>

      <div style={{ marginBottom: 24 }}>
        <PublishAnalytics />
      </div>

      <div className={styles.header}>
        <div style={{ flex: 1 }} />
        <div className={styles.periodToggle}>
          {(["7d", "14d", "30d"] as Period[]).map((p) => (
            <button
              key={p}
              className={`${styles.periodBtn} ${period === p ? styles.periodBtnActive : ""}`}
              onClick={() => setPeriod(p)}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.kpiRow}>
        {kpiCards.map(({ label, value, fmt }) => (
          <div key={label} className={styles.kpiCard}>
            <span className={styles.kpiValue}>{fmt(value)}</span>
            <span className={styles.kpiLabel}>{label}</span>
          </div>
        ))}
      </div>

      <div className={styles.chartFull}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Videos Published</div>
          <MetricChart option={{ type: "area", series: videosSeries, labels, height: 200 }} />
        </div>
      </div>

      <div className={styles.chartRow}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Revenue vs Cost</div>
          <MetricChart option={{ type: "line", series: revSeries, labels, height: 180 }} />
        </div>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Niche Distribution</div>
          <MetricChart option={{ type: "donut", series: nicheSeries, height: 180 }} />
        </div>
      </div>

      <div className={styles.chartRow}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Active Accounts</div>
          <MetricChart option={{ type: "bar", series: accountsSeries, labels, height: 180 }} />
        </div>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Jobs Completed</div>
          <MetricChart option={{ type: "line", series: jobsSeries, labels, height: 180 }} />
        </div>
      </div>

      {/* ─── Performance Analytics ────────────────────────────────────────────── */}

      <div className={styles.sectionDivider}>{t("analytics_performance")}</div>

      <div className={styles.kpiRow}>
        {[
          { label: t("analytics_total_views"), value: perfKpis.total_views, fmt: fmtCompact },
          { label: t("analytics_avg_views"), value: perfKpis.avg_views_per_video, fmt: fmtCompact },
          { label: t("analytics_link_clicks"), value: perfKpis.total_link_clicks, fmt: fmtCompact },
          {
            label: t("analytics_conversion"),
            value: perfKpis.conversion_rate,
            fmt: (v: number) => `${v}%`,
          },
        ].map(({ label, value, fmt }) => (
          <div key={label} className={styles.kpiCard}>
            <span className={styles.kpiValue}>{fmt(value)}</span>
            <span className={styles.kpiLabel}>{label}</span>
          </div>
        ))}
      </div>

      {conversionHistory.length > 0 && (
        <div className={styles.chartFull}>
          <div className={styles.chartCard}>
            <div className={styles.chartTitle}>{t("analytics_views_clicks")}</div>
            <MetricChart
              option={{
                type: "area",
                series: [
                  {
                    name: t("analytics_total_views"),
                    data: conversionHistory.map((p) => p.views),
                    color: "var(--accent-cyan)",
                  },
                  {
                    name: t("analytics_link_clicks"),
                    data: conversionHistory.map((p) => p.link_clicks),
                    color: "var(--accent-pink)",
                  },
                ],
                labels: conversionHistory.map((p) =>
                  new Date(p.ts).toLocaleDateString("en", { month: "short", day: "numeric" })
                ),
                height: 200,
              }}
            />
          </div>
        </div>
      )}

      <div className={styles.chartRow}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>{t("analytics_top_accounts")}</div>
          {accountStats.length > 0 ? (
            <Leaderboard
              items={accountStats.map((a) => ({ label: a.username, value: a.total_views }))}
            />
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
              {t("analytics_no_data")}
            </div>
          )}
        </div>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>{t("analytics_traffic_sources")}</div>
          {trafficSources.length > 0 ? (
            <MetricChart
              option={{
                type: "donut",
                series: trafficSources.map((s) => ({
                  name: s.source,
                  data: [s.percentage],
                  color:
                    s.source === "FYP"
                      ? "var(--accent-cyan)"
                      : s.source === "Following"
                        ? "var(--accent-pink)"
                        : s.source === "Search"
                          ? "var(--accent-amber)"
                          : s.source === "Profile"
                            ? "var(--color-success)"
                            : s.source === "Hashtag"
                              ? "var(--accent-purple)"
                              : "var(--text-muted)",
                })),
                height: 180,
              }}
            />
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
              {t("analytics_no_data")}
            </div>
          )}
        </div>
      </div>

      <div className={styles.chartRow}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>{t("analytics_top_videos")}</div>
          {topVideos.length > 0 ? (
            <Leaderboard
              items={topVideos.map((v) => ({
                label: v.title,
                sublabel: v.account_id,
                value: v.views,
              }))}
              color="var(--accent-pink)"
            />
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
              {t("analytics_no_data")}
            </div>
          )}
        </div>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>{t("analytics_conversion_funnel")}</div>
          {conversionHistory.length > 0 ? (
            <MetricChart
              option={{
                type: "line",
                series: [
                  {
                    name: t("analytics_conversion"),
                    data: conversionHistory.map((p) => p.conversion_rate),
                    color: "var(--color-success)",
                  },
                ],
                labels: conversionHistory.map((p) =>
                  new Date(p.ts).toLocaleDateString("en", { month: "short", day: "numeric" })
                ),
                height: 180,
              }}
            />
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
              {t("analytics_no_data")}
            </div>
          )}
        </div>
      </div>
      {/* ─── Cost Analytics ───────────────────────────────────────────────────── */}

      <div className={styles.sectionDivider}>Cost Analytics</div>

      {costReport ? (
        <>
          <div className={styles.kpiRow}>
            <div className={styles.kpiCard}>
              <span className={styles.kpiValue} style={{ color: "var(--accent-cyan)" }}>
                ${costReport.total.total_usd.toFixed(2)}
              </span>
              <span className={styles.kpiLabel}>Total Spent (all time)</span>
              <span className={styles.kpiSub}>{costReport.total.jobs_count} jobs</span>
            </div>
            {Object.entries(costReport.services).map(([svc, stats]) => (
              <div key={svc} className={styles.kpiCard}>
                <span
                  className={styles.kpiValue}
                  style={{ color: svc === "sportzavod" ? "#d4af37" : svc === "agentmusic" ? "#00c8dc" : "#b496ff" }}
                >
                  ${stats.total_usd.toFixed(2)}
                </span>
                <span className={styles.kpiLabel}>
                  {svc === "sportzavod" ? "SportZavod" : svc === "agentmusic" ? "agentMUSIC" : "content-zavod"}
                </span>
                <span className={styles.kpiSub}>
                  {stats.videos_count} videos · {stats.jobs_count} jobs
                </span>
              </div>
            ))}
            <div className={styles.kpiCard}>
              <span className={styles.kpiValue}>
                ${costReport.total.avg_usd_per_video.toFixed(3)}
              </span>
              <span className={styles.kpiLabel}>Avg Cost / Video</span>
              <span className={styles.kpiSub}>{costReport.total.videos_count} videos total</span>
            </div>
          </div>

          {Object.keys(costReport.services).length > 0 && (
            <div className={styles.chartRow}>
              <div className={styles.chartCard}>
                <div className={styles.chartTitle}>Cost by Service</div>
                {Object.values(costReport.services).some((s) => s.total_usd > 0) ? (
                  <MetricChart
                    option={{
                      type: "donut",
                      series: Object.entries(costReport.services).map(([svc, stats]) => ({
                        name: svc === "sportzavod" ? "SportZavod" : svc === "agentmusic" ? "agentMUSIC" : "content-zavod",
                        data: [+stats.total_usd.toFixed(4)],
                        color: svc === "sportzavod" ? "#d4af37" : svc === "agentmusic" ? "#00c8dc" : "#b496ff",
                      })),
                      height: 180,
                    }}
                  />
                ) : (
                  <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
                    No cost data yet — costs accumulate when content-zavod jobs complete
                  </div>
                )}
              </div>
              <div className={styles.chartCard}>
                <div className={styles.chartTitle}>Avg Cost / Video by Service</div>
                <MetricChart
                  option={{
                    type: "bar",
                    series: [
                      {
                        name: "Avg $/video",
                        data: Object.entries(costReport.services).map(
                          ([, s]) => +s.avg_usd_per_video.toFixed(4)
                        ),
                        color: "var(--accent-cyan)",
                      },
                    ],
                    labels: Object.keys(costReport.services).map((svc) =>
                      svc === "sportzavod" ? "SportZavod" : "content-zavod"
                    ),
                    height: 180,
                  }}
                />
              </div>
            </div>
          )}
        </>
      ) : (
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>No cost data yet</div>
      )}

      {/* ─── Generation Speed ─────────────────────────────────────────────────── */}

      <div className={styles.sectionDivider}>{t("analytics_gen_speed")}</div>

      {Object.keys(generationStats).length > 0 ? (
        <div className={styles.kpiRow}>
          {Object.entries(generationStats).map(([svc, stats]) => (
            <div key={svc} className={styles.kpiCard}>
              <span
                className={styles.kpiValue}
                style={{ color: svc === "sportzavod" ? "#d4af37" : svc === "agentmusic" ? "#00c8dc" : "#b496ff" }}
              >
                {fmtSec(stats.avg_sec)}
              </span>
              <span className={styles.kpiLabel}>
                {svc === "sportzavod" ? "SportZavod" : svc === "agentmusic" ? "agentMUSIC" : "content-zavod"}
              </span>
              <span className={styles.kpiSub}>
                {stats.count} {t("analytics_gen_jobs")}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{t("analytics_gen_no_data")}</div>
      )}
    </div>
  );
}

function fmtSec(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
}

function asPercent(value: number): number {
  return Math.abs(value) <= 1 ? value * 100 : value;
}

function fmtCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
