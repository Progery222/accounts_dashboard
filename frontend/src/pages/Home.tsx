import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSummary, type Summary, type PlatformSummary } from "../api/accounts";
import PlatformIcon from "../components/PlatformIcon";

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return n.toString();
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-zinc-600 text-xs">—</span>;
  if (value === 0) return <span className="text-zinc-500 text-xs">0</span>;
  const positive = value > 0;
  return (
    <span className={`text-xs font-medium ${positive ? "text-emerald-400" : "text-red-400"}`}>
      {positive ? "+" : ""}{fmt(value)}
    </span>
  );
}


function StatCard({
  label,
  value,
  delta,
}: {
  label: string;
  value: number;
  delta: number | null;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col gap-1">
      <span className="text-zinc-500 text-xs uppercase tracking-wider">{label}</span>
      <span className="text-white text-3xl font-bold">{fmt(value)}</span>
      <div className="flex items-center gap-1 text-zinc-500 text-xs">
        <span>за сутки:</span>
        <Delta value={delta} />
      </div>
    </div>
  );
}

function PlatformRow({ p }: { p: PlatformSummary }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-zinc-800 last:border-0">
      <div className="flex items-center gap-2 text-zinc-300 min-w-[110px]">
        <PlatformIcon platform={p.platform} className="w-4 h-4 text-zinc-500 shrink-0" />
        <span className="text-sm font-medium">{p.platform_label}</span>
        <span className="text-zinc-600 text-xs">×{p.account_count}</span>
      </div>
      <div className="flex gap-6 text-sm text-zinc-400">
        <div className="text-right">
          <div className="text-white font-medium">{fmt(p.follower_count)}</div>
          <div className="text-zinc-600 text-xs">подписчики</div>
        </div>
        <div className="text-right">
          <div className="text-white font-medium">{fmt(p.view_count)}</div>
          <div className="text-zinc-600 text-xs">просмотры</div>
        </div>
        <div className="text-right">
          <div className="text-white font-medium">{fmt(p.like_count)}</div>
          <div className="text-zinc-600 text-xs">лайки</div>
        </div>
        <div className="text-right">
          <div className="text-white font-medium">{fmt(p.post_count)}</div>
          <div className="text-zinc-600 text-xs">публикации</div>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const { data, isLoading } = useQuery<Summary>({
    queryKey: ["summary"],
    queryFn: getSummary,
    staleTime: 60_000,
  });

  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-3xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-bold tracking-tight">AccountsStats</h1>
          <p className="text-zinc-500 mt-1 text-sm">Общая статистика по всем аккаунтам</p>
        </div>

        {isLoading || !data ? (
          <div className="text-zinc-600 text-sm">Загрузка...</div>
        ) : data.account_count === 0 ? (
          <div className="text-zinc-500 text-sm">
            Аккаунты не добавлены.{" "}
            <Link to="/accounts" className="text-white underline">
              Добавить
            </Link>
          </div>
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="Подписчики"
                value={data.follower_count}
                delta={data.follower_delta}
              />
              <StatCard
                label="Просмотры"
                value={data.view_count}
                delta={data.view_delta}
              />
              <StatCard
                label="Лайки"
                value={data.like_count}
                delta={data.like_delta}
              />
              <StatCard
                label="Публикации"
                value={data.post_count}
                delta={data.post_delta}
              />
            </div>

            {/* Per-platform breakdown */}
            {data.by_platform.length > 0 && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-2 mb-8">
                {data.by_platform.map((p) => (
                  <PlatformRow key={p.platform} p={p} />
                ))}
              </div>
            )}

            {/* Navigation links */}
            <div className="flex gap-4">
              <Link
                to="/accounts"
                className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Все аккаунты ({data.account_count})
              </Link>
              <Link
                to="/analytics"
                className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                Аналитика
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
