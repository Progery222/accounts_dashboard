import { useId, useMemo, useState } from "react";

export type PresumedStatItem = { label: string; count: number; rank: number };

export type PresumedStatColumn = { header: string; items: PresumedStatItem[] };

export type PresumedStatsResponse = {
  generated_at: string | null;
  columns: PresumedStatColumn[];
};

/** Базовые цвета сегментов (к градиенту добавляется более светлый «блик»). */
const PIE_COLORS = [
  "#5eb8f0",
  "#9b7bed",
  "#3dce6f",
  "#f0627a",
  "#eab308",
  "#2ea8e6",
  "#b070f0",
  "#2bbd8a",
  "#ec6b9a",
  "#e5a50a",
];

/** Склонение «N подписчик(а/ов)» для подсчёта людей в срезе CSV. */
export function ruSubscribersCountPhrase(n: number): string {
  const abs = Math.abs(Math.trunc(n));
  const mod100 = abs % 100;
  const mod10 = abs % 10;
  let word: string;
  if (mod10 === 1 && mod100 !== 11) word = "подписчик";
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) word = "подписчика";
  else word = "подписчиков";
  return `${abs} ${word}`;
}

function pieSegmentsForChart(items: PresumedStatItem[], maxSlices = 8): { label: string; count: number }[] {
  if (!items.length) return [];
  if (items.length <= maxSlices) {
    return items.map((i) => ({ label: i.label, count: i.count }));
  }
  const head = items.slice(0, maxSlices - 1);
  const rest = items.slice(maxSlices - 1);
  const other = rest.reduce((s, x) => s + x.count, 0);
  return [...head.map((i) => ({ label: i.label, count: i.count })), { label: "Прочее", count: other }];
}

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

/** Кольцо: r1 внешний, r0 внутренний. */
function donutSectorPath(
  cx: number,
  cy: number,
  r0: number,
  r1: number,
  startDeg: number,
  endDeg: number,
): string {
  const delta = endDeg - startDeg;
  const largeArc = delta > 180 ? 1 : 0;
  const [x1, y1] = polar(cx, cy, r1, startDeg);
  const [x2, y2] = polar(cx, cy, r1, endDeg);
  const [x3, y3] = polar(cx, cy, r0, endDeg);
  const [x4, y4] = polar(cx, cy, r0, startDeg);
  return [
    `M ${x1} ${y1}`,
    `A ${r1} ${r1} 0 ${largeArc} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${r0} ${r0} 0 ${largeArc} 0 ${x4} ${y4}`,
    `Z`,
  ].join(" ");
}

function PieChart({ segments }: { segments: { label: string; count: number }[] }) {
  const reactId = useId().replace(/:/g, "");
  const total = segments.reduce((s, x) => s + x.count, 0);
  if (total <= 0) {
    return (
      <div className="subs-pie-empty">
        Нет данных для диаграммы
      </div>
    );
  }
  const rOuter = 88;
  const rInner = 54;
  let angle = 0;
  const paths = segments.map((seg, i) => {
    const sweep = (seg.count / total) * 360;
    const start = angle;
    const end = angle + sweep;
    angle = end;
    const base = PIE_COLORS[i % PIE_COLORS.length];
    return {
      d: donutSectorPath(0, 0, rInner, rOuter, start, end),
      base,
      gradId: `subs-pie-g-${reactId}-${i}`,
      label: seg.label,
      count: seg.count,
    };
  });

  return (
    <div className="subs-pie-frame">
      <svg viewBox="-100 -100 200 200" className="subs-pie-svg" role="img" aria-label="Кольцевая диаграмма">
        <defs>
          {paths.map((p) => (
            <linearGradient key={p.gradId} id={p.gradId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={p.base} stopOpacity={0.55} />
              <stop offset="42%" stopColor={p.base} stopOpacity={1} />
              <stop offset="100%" stopColor={p.base} stopOpacity={0.88} />
            </linearGradient>
          ))}
        </defs>
        {/* лёгкая подложка под кольцо */}
        <circle cx="0" cy="0" r={rOuter + 2} className="subs-pie-backdrop" />
        {paths.map((p, i) => (
          <path
            key={`${p.label}-${i}`}
            d={p.d}
            fill={`url(#${p.gradId})`}
            stroke="rgba(255,255,255,0.14)"
            strokeWidth={1.25}
            strokeLinejoin="round"
            className="subs-pie-segment"
          />
        ))}
      </svg>
      <div className="subs-pie-center" aria-hidden>
        <span className="subs-pie-center__n tnum">{total}</span>
        <span className="subs-pie-center__l">в срезе</span>
      </div>
    </div>
  );
}

function ColumnSection({
  column,
  listExpanded,
  onToggleList,
}: {
  column: PresumedStatColumn;
  listExpanded: boolean;
  onToggleList: () => void;
}) {
  const chartSlices = useMemo(() => pieSegmentsForChart(column.items), [column.items]);
  const legendRows = useMemo(() => {
    const sum = chartSlices.reduce((s, x) => s + x.count, 0) || 1;
    return chartSlices.map((row, i) => ({
      row,
      i,
      pct: Math.round((row.count / sum) * 1000) / 10,
      color: PIE_COLORS[i % PIE_COLORS.length],
    }));
  }, [chartSlices]);
  const top3 = column.items.slice(0, 3);
  const rest = column.items.slice(3);

  if (!column.items.length) {
    return (
      <section className="subs-presumed-col">
        <h4 className="subs-presumed-col__title">{column.header}</h4>
        <p className="subs-muted" style={{ margin: 0, fontSize: 13 }}>
          Нет заполненных значений (все пустые или «Нет данных»).
        </p>
      </section>
    );
  }

  return (
    <section className="subs-presumed-col">
      <h4 className="subs-presumed-col__title">{column.header}</h4>
      <div className="subs-presumed-col__body">
        <div className="subs-presumed-pie-wrap">
          <PieChart segments={chartSlices} />
        </div>
        <div className="subs-presumed-legend">
          {legendRows.map(({ row, i, pct, color }) => (
            <div key={`${row.label}-${i}`} className="subs-presumed-legend__row">
              <span
                className="subs-presumed-legend__swatch"
                style={{
                  background: `linear-gradient(145deg, ${color}cc 0%, ${color} 55%, ${color}99 100%)`,
                  boxShadow: `0 0 0 1px rgba(255,255,255,0.12), 0 2px 8px ${color}33`,
                }}
              />
              <span className="subs-presumed-legend__label" title={row.label}>
                {row.label}
              </span>
              <span className="subs-presumed-legend__meta">
                <span className="subs-presumed-legend__count tnum">{row.count}</span>
                <span className="subs-presumed-legend__pct tnum">{pct}%</span>
              </span>
            </div>
          ))}
        </div>
      </div>
      <ul className="subs-presumed-top">
        {top3.map((it, idx) => (
          <li key={`top-${idx}-${it.label}`} className="subs-presumed-top__li">
            <span className="tnum">{it.rank}</span>. {it.label} — {ruSubscribersCountPhrase(it.count)}
          </li>
        ))}
      </ul>
      {rest.length > 0 ? (
        <div className="subs-presumed-more">
          <button
            type="button"
            className="subs-btn subs-btn--sm subs-btn--muted"
            aria-expanded={listExpanded}
            onClick={onToggleList}
          >
            {listExpanded ? "Свернуть" : "Весь список"}
          </button>
          {listExpanded ? (
            <ul className="subs-presumed-rest">
              {rest.map((it, idx) => (
                <li key={`rest-${idx}-${it.label}`} className="subs-presumed-rest__li">
                  <span className="tnum">{it.rank}</span>. {it.label} — {ruSubscribersCountPhrase(it.count)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function PresumedChartsPanel({
  data,
  loading,
  error,
  onRetry,
}: {
  data: PresumedStatsResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  /** Раскрытие «Весь список» отдельно для каждой колонки (ключ — заголовок). */
  const [listExpandedByHeader, setListExpandedByHeader] = useState<Record<string, boolean>>({});

  const toggleListForHeader = (header: string) => {
    setListExpandedByHeader((prev) => ({ ...prev, [header]: !prev[header] }));
  };

  if (loading) {
    return <p style={{ margin: "18px 0", color: "var(--ink-dim)" }}>Загрузка графиков…</p>;
  }
  if (error) {
    return (
      <div style={{ margin: "18px 0" }}>
        <p style={{ color: "var(--danger)", margin: "0 0 10px" }}>{error}</p>
        <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={onRetry}>
          Повторить
        </button>
      </div>
    );
  }
  if (!data?.columns?.length) {
    return (
      <p className="subs-muted" style={{ margin: "18px 0" }}>
        Нет колонок для отображения.
      </p>
    );
  }

  return (
    <div className="subs-presumed-charts-root">
      {data.columns.map((col, colIndex) => (
        <ColumnSection
          key={`${colIndex}-${col.header}`}
          column={col}
          listExpanded={Boolean(listExpandedByHeader[col.header])}
          onToggleList={() => toggleListForHeader(col.header)}
        />
      ))}
    </div>
  );
}
