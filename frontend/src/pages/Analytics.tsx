import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  getTopPosts, getInsights,
  type Period, type SortBy, type AnalyticsPost,
  type PlatformStat, type HashtagStat, type HourStat, type WeekdayStat,
} from "../api/analytics";
import { getPlatforms, type Platform } from "../api/accounts";
import PlatformIcon from "../components/PlatformIcon";

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

function fmtDelta(n: number): string {
  const abs = Math.abs(n);
  const s = abs >= 1_000_000 ? (abs / 1_000_000).toFixed(1) + "M"
    : abs >= 1_000 ? (abs / 1_000).toFixed(1) + "K"
    : String(abs);
  return (n >= 0 ? "+" : "−") + s;
}


const PERIOD_LABELS: Record<Period, string> = {
  "1d": "Сутки", "7d": "7 дней", "30d": "30 дней", "all": "Всё время",
};

const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: "view_delta", label: "Прирост просмотров" },
  { value: "like_delta", label: "Прирост лайков" },
  { value: "views",      label: "Просмотры (всего)" },
  { value: "likes",      label: "Лайки (всего)" },
  { value: "comments",   label: "Комментарии" },
  { value: "shares",     label: "Репосты" },
  { value: "er",         label: "Вовлечённость (ER)" },
];

// ─── sub-components ──────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-base font-semibold text-zinc-200 mb-3">{children}</h2>;
}

function Pill({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
        active
          ? "bg-white text-black"
          : "bg-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-700"
      }`}
    >
      {children}
    </button>
  );
}

function PostRow({ post, sortBy }: { post: AnalyticsPost; sortBy: SortBy }) {
  const mainValue =
    sortBy === "view_delta" ? post.view_delta
    : sortBy === "like_delta" ? post.like_delta
    : sortBy === "views"    ? post.view_count
    : sortBy === "likes"    ? post.like_count
    : sortBy === "comments" ? post.comment_count
    : sortBy === "shares"   ? post.share_count
    : null;

  return (
    <a
      href={post.post_url || "#"}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-start gap-3 px-4 py-3 hover:bg-zinc-800/60 transition-colors rounded-xl group"
    >
      {/* Thumbnail */}
      <div className="shrink-0 w-14 h-14 rounded-lg overflow-hidden bg-zinc-800 border border-zinc-700">
        {post.thumbnail_url ? (
          <img src={post.thumbnail_url} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-600">
            <PlatformIcon platform={post.account.platform} className="w-6 h-6" />
          </div>
        )}
      </div>

      {/* Main info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          <PlatformIcon platform={post.account.platform} className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
          <span className="text-xs text-zinc-500 truncate">@{post.account.username}</span>
          {post.posted_at && (
            <span className="text-xs text-zinc-700 ml-auto shrink-0">
              {new Date(post.posted_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" })}
            </span>
          )}
        </div>
        {post.description ? (
          <p className="text-sm text-zinc-300 line-clamp-1">{post.description}</p>
        ) : (
          <p className="text-sm text-zinc-600 italic">Без описания</p>
        )}
        {post.hashtags.length > 0 && (
          <div className="flex gap-1 mt-0.5 flex-wrap">
            {post.hashtags.slice(0, 4).map(t => (
              <span key={t} className="text-xs text-blue-400/70">#{t}</span>
            ))}
            {post.hashtags.length > 4 && (
              <span className="text-xs text-zinc-600">+{post.hashtags.length - 4}</span>
            )}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="shrink-0 flex flex-col items-end gap-0.5 min-w-[90px]">
        {mainValue !== null && (
          <span className={`text-sm font-semibold ${mainValue > 0 ? "text-emerald-400" : mainValue < 0 ? "text-red-400" : "text-white"}`}>
            {sortBy === "er"
              ? `${post.engagement_rate.toFixed(1)}%`
              : (sortBy === "view_delta" || sortBy === "like_delta") && mainValue !== 0
                ? fmtDelta(mainValue)
                : fmt(mainValue)}
          </span>
        )}
        <div className="flex gap-2 text-xs text-zinc-600">
          <span>👁 {fmt(post.view_count)}</span>
          <span>❤️ {fmt(post.like_count)}</span>
        </div>
        <span className="text-xs text-zinc-700">ER {post.engagement_rate.toFixed(1)}%</span>
      </div>
    </a>
  );
}

function PlatformTable({ data }: { data: PlatformStat[] }) {
  if (!data.length) return <p className="text-zinc-600 text-sm">Нет данных</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-zinc-500 border-b border-zinc-800">
            <th className="text-left py-2 pr-4 font-normal">Платформа</th>
            <th className="text-right py-2 px-4 font-normal">Постов</th>
            <th className="text-right py-2 px-4 font-normal">Avg просмотры</th>
            <th className="text-right py-2 px-4 font-normal">Avg лайки</th>
            <th className="text-right py-2 pl-4 font-normal">Avg ER</th>
          </tr>
        </thead>
        <tbody>
          {data.map(p => (
            <tr key={p.platform} className="border-b border-zinc-800/50 last:border-0">
              <td className="py-2.5 pr-4 text-zinc-300">
                <PlatformIcon platform={p.platform} className="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
              {p.platform_label}
              </td>
              <td className="text-right px-4 text-zinc-400">{p.post_count}</td>
              <td className="text-right px-4 text-white font-medium">{fmt(p.avg_views)}</td>
              <td className="text-right px-4 text-white">{fmt(p.avg_likes)}</td>
              <td className="text-right pl-4 text-emerald-400">{p.avg_er.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const HASHTAGS_PER_PAGE = 24;

type HtSort = "count" | "avg_views" | "avg_er" | "avg_likes";

const HT_SORT_LABELS: Record<HtSort, string> = {
  count:     "Постов",
  avg_views: "Просмотры",
  avg_likes: "Лайки",
  avg_er:    "ER",
};

function HashtagCloud({
  data,
  selected,
  onSelect,
}: {
  data: HashtagStat[];
  selected: string;
  onSelect: (tag: string) => void;
}) {
  const [htPage, setHtPage] = useState(1);
  const [htSort, setHtSort] = useState<HtSort>("count");

  const changeSort = (s: HtSort) => { setHtSort(s); setHtPage(1); };

  if (!data.length)
    return <p className="text-zinc-600 text-sm">Хэштегов нет — обнови аккаунты</p>;

  const sorted = [...data].sort((a, b) => b[htSort] - a[htSort]);
  const totalPages = Math.ceil(sorted.length / HASHTAGS_PER_PAGE);
  const slice = sorted.slice((htPage - 1) * HASHTAGS_PER_PAGE, htPage * HASHTAGS_PER_PAGE);

  return (
    <div>
      {/* ── Sort controls ── */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {(Object.keys(HT_SORT_LABELS) as HtSort[]).map(s => (
          <button
            key={s}
            onClick={() => changeSort(s)}
            className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${
              htSort === s
                ? "bg-white/10 text-white border border-white/20"
                : "bg-zinc-800 text-zinc-400 border border-transparent hover:text-white"
            }`}
          >
            {HT_SORT_LABELS[s]}
          </button>
        ))}
      </div>

      {/* ── Tag grid ── */}
      <div className="flex flex-wrap gap-2">
        {slice.map(t => {
          const isActive = selected === t.tag;
          return (
            <button
              key={t.tag}
              onClick={() => onSelect(isActive ? "" : t.tag)}
              className={`text-left px-2.5 py-1.5 rounded-xl border transition-colors ${
                isActive
                  ? "bg-white/10 border-white/30 text-white"
                  : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-white"
              }`}
            >
              <div className="text-xs font-medium">
                #{t.tag}
                <span className={`ml-1.5 ${isActive ? "text-white/50" : "text-zinc-600"}`}>
                  {t.count}
                </span>
              </div>
              <div className={`text-xs mt-0.5 flex gap-2 ${isActive ? "text-white/60" : "text-zinc-500"}`}>
                <span>{fmt(t.avg_views)} просм.</span>
                <span className="text-emerald-500/80">ER {t.avg_er}%</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* ── Pagination ── */}
      {totalPages > 1 && (
        <div className="flex items-center gap-1 mt-3">
          <button
            onClick={() => setHtPage(p => Math.max(1, p - 1))}
            disabled={htPage === 1}
            className="px-2.5 py-1 rounded-lg text-sm bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30 transition-colors"
          >←</button>
          <span className="text-xs text-zinc-600 px-2">
            {htPage} / {totalPages} · {sorted.length} хэштегов
          </span>
          <button
            onClick={() => setHtPage(p => Math.min(totalPages, p + 1))}
            disabled={htPage === totalPages}
            className="px-2.5 py-1 rounded-lg text-sm bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30 transition-colors"
          >→</button>
        </div>
      )}

      {/* ── Active filter hint ── */}
      {selected && (
        <p className="text-xs text-zinc-500 mt-2">
          Показаны посты с <span className="text-white">#{selected}</span>.{" "}
          <button onClick={() => onSelect("")} className="text-zinc-400 underline hover:text-white">
            Сбросить
          </button>
        </p>
      )}
    </div>
  );
}

function HourGrid({ data }: { data: HourStat[] }) {
  const maxViews = Math.max(...data.map(h => h.avg_views), 1);
  return (
    <div>
      <div className="grid grid-cols-12 gap-1 mb-1">
        {data.slice(0, 12).map(h => (
          <HourCell key={h.hour} h={h} maxViews={maxViews} />
        ))}
      </div>
      <div className="grid grid-cols-12 gap-1">
        {data.slice(12).map(h => (
          <HourCell key={h.hour} h={h} maxViews={maxViews} />
        ))}
      </div>
      <div className="flex justify-between text-xs text-zinc-600 mt-1 px-0.5">
        <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:00</span>
      </div>
      <p className="text-xs text-zinc-600 mt-1">Яркость = avg просмотры. Наведи для деталей.</p>
    </div>
  );
}

function HourCell({ h, maxViews }: { h: HourStat; maxViews: number }) {
  const intensity = h.post_count > 0 ? Math.max(0.08, h.avg_views / maxViews) : 0;
  const bg = h.post_count === 0
    ? "bg-zinc-800"
    : `bg-emerald-500`;
  return (
    <div
      className={`${bg} rounded aspect-square cursor-default`}
      style={{ opacity: h.post_count === 0 ? 0.3 : intensity }}
      title={`${h.hour}:00 · ${h.post_count} постов · avg ${fmt(h.avg_views)} просм. · ER ${h.avg_er}%`}
    />
  );
}

function WeekdayBar({ data }: { data: WeekdayStat[] }) {
  const maxViews = Math.max(...data.map(d => d.avg_views), 1);
  return (
    <div className="flex gap-2 items-end h-24">
      {data.map(d => {
        const pct = d.post_count > 0 ? Math.max(8, (d.avg_views / maxViews) * 100) : 0;
        return (
          <div key={d.weekday} className="flex-1 flex flex-col items-center gap-1">
            <div
              className="w-full rounded-t bg-blue-500/70 transition-all"
              style={{ height: `${pct}%` }}
              title={`${d.weekday_label} · ${d.post_count} постов · avg ${fmt(d.avg_views)} просм. · ER ${d.avg_er}%`}
            />
            <span className="text-xs text-zinc-500">{d.weekday_label}</span>
          </div>
        );
      })}
    </div>
  );
}

function Pagination({
  page, pages, onChange,
}: { page: number; pages: number; onChange: (p: number) => void }) {
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-1 pt-4">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page === 1}
        className="px-3 py-1.5 rounded-lg text-sm bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30 transition-colors"
      >←</button>
      {Array.from({ length: Math.min(pages, 7) }, (_, i) => {
        const p = pages <= 7 ? i + 1 : page <= 4 ? i + 1 : page >= pages - 3 ? pages - 6 + i : page - 3 + i;
        return (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              p === page ? "bg-white text-black font-semibold" : "bg-zinc-800 text-zinc-400 hover:text-white"
            }`}
          >{p}</button>
        );
      })}
      <button
        onClick={() => onChange(page + 1)}
        disabled={page === pages}
        className="px-3 py-1.5 rounded-lg text-sm bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30 transition-colors"
      >→</button>
    </div>
  );
}

// ─── main page ───────────────────────────────────────────────────────────────

export default function Analytics({ accountId }: { accountId?: number }) {
  const [period, setPeriod]       = useState<Period>("1d");
  const [sortBy, setSortBy]       = useState<SortBy>("view_delta");
  const [platform, setPlatform]   = useState<string>("");
  const [page, setPage]           = useState(1);
  const [selectedHashtag, setSelectedHashtag] = useState<string>("");

  // Reset page when filters change
  const handlePeriod   = (p: Period)   => { setPeriod(p);   setPage(1); };
  const handleSort     = (s: SortBy)   => { setSortBy(s);   setPage(1); };
  const handlePlatform = (pl: string)  => { setPlatform(pl); setPage(1); };
  const handleHashtag  = (tag: string) => { setSelectedHashtag(tag); setPage(1); };

  const params = {
    period,
    platform: platform || undefined,
    account_id: accountId,
    min_views: 10,
  };

  const { data: topData, isFetching: topLoading } = useQuery({
    queryKey: ["analytics-top", period, sortBy, platform, accountId, page, selectedHashtag],
    queryFn: () => getTopPosts({
      ...params,
      sort_by: sortBy,
      page,
      page_size: 20,
      hashtag: selectedHashtag || undefined,
    }),
    staleTime: 60_000,
  });

  const { data: ins, isFetching: insLoading } = useQuery({
    queryKey: ["analytics-insights", period, platform, accountId],
    queryFn: () => getInsights(params),
    staleTime: 60_000,
  });

  const { data: platformList = [] } = useQuery<Platform[]>({
    queryKey: ["platforms"],
    queryFn: getPlatforms,
    staleTime: Infinity,
  });

  const isEmbedded = accountId !== undefined;

  return (
    <div className={isEmbedded ? "" : "min-h-screen bg-black text-white"}>
      {!isEmbedded && (
        <header className="sticky top-0 z-10 bg-black/80 backdrop-blur border-b border-zinc-800 px-4 py-3">
          <div className="max-w-5xl mx-auto flex items-center gap-4">
            <Link to="/" className="text-zinc-400 hover:text-white transition-colors flex items-center gap-2 text-sm">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
              Главная
            </Link>
            <span className="text-zinc-600">/</span>
            <span className="text-zinc-300 font-medium">Аналитика</span>
          </div>
        </header>
      )}

      <div className={isEmbedded ? "pt-6" : "max-w-5xl mx-auto px-4 py-8"}>

        {/* ── Controls ── */}
        <div className="flex flex-wrap gap-3 mb-6 items-center">
          {/* Period */}
          <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
            {(["1d", "7d", "30d", "all"] as Period[]).map(p => (
              <Pill key={p} active={period === p} onClick={() => handlePeriod(p)}>
                {PERIOD_LABELS[p]}
              </Pill>
            ))}
          </div>

          {/* Platform filter (only in global mode) */}
          {!isEmbedded && platformList.length > 0 && (
            <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
              <Pill active={platform === ""} onClick={() => handlePlatform("")}>Все</Pill>
              {platformList.map(pl => (
                <Pill key={pl.value} active={platform === pl.value} onClick={() => handlePlatform(pl.value)}>
                  <PlatformIcon platform={pl.value} className="w-3.5 h-3.5 inline-block mr-1 -mt-0.5" />
                  {pl.label}
                </Pill>
              ))}
            </div>
          )}
        </div>

        {/* ── Top posts ── */}
        <section className="bg-zinc-900 border border-zinc-800 rounded-2xl mb-5 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4 pb-3 border-b border-zinc-800">
            <SectionTitle>
              Топ постов
              {topData && <span className="ml-2 text-sm text-zinc-500 font-normal">({topData.total})</span>}
              {selectedHashtag && (
                <button
                  onClick={() => handleHashtag("")}
                  className="ml-2 text-xs font-normal text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded-full hover:text-white transition-colors"
                >
                  #{selectedHashtag} ×
                </button>
              )}
            </SectionTitle>
            <select
              value={sortBy}
              onChange={e => handleSort(e.target.value as SortBy)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-300 focus:outline-none focus:border-zinc-500"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          {topLoading && !topData && (
            <div className="flex justify-center py-10">
              <div className="w-6 h-6 border-2 border-zinc-600 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {topData?.items.length === 0 && (
            <p className="text-zinc-600 text-sm px-4 py-8 text-center">
              Нет постов с ≥10 просмотрами за выбранный период
            </p>
          )}

          {topData && topData.items.length > 0 && (
            <>
              <div className={`divide-y divide-zinc-800/50 ${topLoading ? "opacity-60" : ""}`}>
                {topData.items.map(p => (
                  <PostRow key={p.id} post={p} sortBy={sortBy} />
                ))}
              </div>
              <div className="px-4 pb-4">
                <Pagination page={topData.page} pages={topData.pages} onChange={setPage} />
              </div>
            </>
          )}
        </section>

        {/* ── Platform comparison ── */}
        {!isEmbedded && (
          <section className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4 mb-5">
            <SectionTitle>Сравнение платформ</SectionTitle>
            {insLoading && !ins
              ? <div className="text-zinc-600 text-sm">Загрузка...</div>
              : <PlatformTable data={ins?.platform_comparison ?? []} />
            }
          </section>
        )}

        {/* ── Hashtags ── */}
        <section className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4 mb-5">
          <SectionTitle>
            Топ хэштегов
            {selectedHashtag && (
              <span className="ml-2 text-xs font-normal text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded-full">
                фильтр: #{selectedHashtag}
              </span>
            )}
          </SectionTitle>
          {insLoading && !ins
            ? <div className="text-zinc-600 text-sm">Загрузка...</div>
            : <HashtagCloud
                data={ins?.top_hashtags ?? []}
                selected={selectedHashtag}
                onSelect={handleHashtag}
              />
          }
        </section>

        {/* ── Best time ── */}
        <section className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4">
          <SectionTitle>Лучшее время для постинга</SectionTitle>
          {insLoading && !ins ? (
            <div className="text-zinc-600 text-sm">Загрузка...</div>
          ) : ins ? (
            <div className="grid md:grid-cols-2 gap-8">
              <div>
                <p className="text-xs text-zinc-500 mb-3 uppercase tracking-wider">По часам (МСК)</p>
                <HourGrid data={ins.best_hours} />
              </div>
              <div>
                <p className="text-xs text-zinc-500 mb-3 uppercase tracking-wider">По дням недели</p>
                <WeekdayBar data={ins.best_weekdays} />
              </div>
            </div>
          ) : null}
        </section>

      </div>
    </div>
  );
}
