import { useState, useRef, useEffect, type ReactNode } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAccount, getAccountPosts, refreshAccount, deleteAccount, updateAccount, type Account, type Post } from "../api/accounts";
import { getProfiles, type Profile } from "../api/profiles";
import Analytics from "./Analytics";
import PlatformIcon from "../components/PlatformIcon";
import { externalProfileUrl } from "../utils/platformUrls";

// Which stats are meaningful for each platform
const PLATFORM_STATS: Record<string, { likes: boolean; views: boolean; posts: boolean }> = {
  tiktok:    { likes: true,  views: true,  posts: true },
  youtube:   { likes: true,  views: true,  posts: true },
  telegram:  { likes: true,  views: true,  posts: true },
  instagram: { likes: true,  views: true,  posts: true },
  threads:   { likes: true,  views: true,  posts: true },
  x:         { likes: true,  views: true,  posts: true },
  facebook:  { likes: true,  views: false, posts: true },
};

// Thumbnail aspect ratio per platform
const THUMB_ASPECT: Record<string, string> = {
  tiktok:    "aspect-[9/16]",
  youtube:   "aspect-video",
  instagram: "aspect-square",
  telegram:  "aspect-video",
  facebook:  "aspect-video",
};

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function fmtDelta(n: number): string {
  const abs = Math.abs(n);
  const s = abs >= 1_000_000 ? (abs / 1_000_000).toFixed(1) + "M"
          : abs >= 1_000 ? (abs / 1_000).toFixed(1) + "K"
          : String(abs);
  return n >= 0 ? "+" + s : "−" + s;
}

function Delta({ value }: { value: number | null }) {
  if (value == null || value === 0) return null;
  return (
    <span className={`text-xs font-medium ml-1 ${value > 0 ? "text-green-400" : "text-red-400"}`}>
      {fmtDelta(value)}
    </span>
  );
}

function displayHandle(platform: string, username: string): string {
  return platform === "rumble" ? username : `@${username}`;
}

const extLinkClass =
  "hover:underline decoration-zinc-500 underline-offset-2 transition-colors hover:text-white";

function ExternalProfileAnchor({
  platform,
  username,
  className,
  children,
}: {
  platform: string;
  username: string;
  className?: string;
  children: ReactNode;
}) {
  const href = externalProfileUrl(platform, username);
  if (!href) {
    return <span className={className}>{children}</span>;
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`${extLinkClass} ${className ?? ""}`.trim()}>
      {children}
    </a>
  );
}

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const accountId = Number(id);
  const isValidAccountId = Number.isFinite(accountId) && accountId > 0;
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data: account, isLoading: accLoading, isError: accError } = useQuery({
    queryKey: ["account", accountId],
    queryFn: () => getAccount(accountId),
    enabled: isValidAccountId,
  });

  const { data: posts = [], isLoading: postsLoading, refetch: refetchPosts } = useQuery({
    queryKey: ["account-posts", accountId],
    queryFn: () => getAccountPosts(accountId),
    enabled: isValidAccountId,
  });

  const { data: profiles = [] } = useQuery({
    queryKey: ["profiles"],
    queryFn: getProfiles,
    staleTime: 30_000,
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshAccount(accountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account", accountId] });
      refetchPosts();
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: () => {
      qc.invalidateQueries({ queryKey: ["account", accountId] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const profileMutation = useMutation({
    mutationFn: (profileId: number | null) =>
      updateAccount(accountId, { profile_id: profileId } as Partial<Account>),
    onSuccess: (updated) => {
      qc.setQueryData(["account", accountId], updated);
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["profiles"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteAccount(accountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      navigate("/accounts");
    },
  });

  const platformStats = PLATFORM_STATS[account?.platform ?? "tiktok"] ?? { likes: true, views: true, posts: true };
  const [tab, setTab] = useState<"posts" | "analytics">("posts");

  return (
    <div className="min-h-screen bg-black text-white">
      <header className="sticky top-0 z-10 bg-black/80 backdrop-blur border-b border-zinc-800 px-4 py-3">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link to="/" className="text-zinc-400 hover:text-white transition-colors flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            <span className="text-sm">Аккаунты</span>
          </Link>
          <span className="text-zinc-600">/</span>
          {account && (
            <ExternalProfileAnchor
              platform={account.platform}
              username={account.username}
              className="text-zinc-300 font-medium truncate inline-flex items-center gap-1.5 max-w-[min(100%,48vw)]"
            >
              <PlatformIcon platform={account.platform} className="w-4 h-4 shrink-0" />
              {displayHandle(account.platform, account.username)}
            </ExternalProfileAnchor>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {!isValidAccountId && (
          <div className="text-center py-20 text-zinc-500">
            <p>Некорректный ID аккаунта в адресе</p>
            <Link to="/accounts" className="text-[#fe2c55] mt-2 inline-block">Назад</Link>
          </div>
        )}

        {accLoading && (
          <div className="flex justify-center py-20">
            <div className="w-8 h-8 border-2 border-[#fe2c55] border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {accError && (
          <div className="text-center py-20 text-zinc-500">
            <p>Аккаунт не найден</p>
            <Link to="/accounts" className="text-[#fe2c55] mt-2 inline-block">Назад</Link>
          </div>
        )}

        {account && (
          <>
            {account.profile_unavailable && (
              <div
                className="mb-6 rounded-xl border border-amber-700/60 bg-amber-950/40 px-4 py-3 text-sm"
                role="status"
              >
                <p className="font-medium text-amber-100">Профиль на площадке недоступен</p>
                <p className="text-amber-100/85 mt-1.5 text-xs leading-relaxed">
                  {account.platform === "instagram"
                    ? "При последнем обновлении Instagram вернул страницу «профиль удалён» или 404. Если аккаунт восстановили, нажмите «Обновить» — статус сбросится."
                    : account.platform === "threads"
                      ? "При последнем обновлении Threads показал страницу «профиль недоступен» (удалён или ссылка не работает). Если профиль снова появился, нажмите «Обновить» — статус сбросится."
                      : "Площадка не отдала данные профиля при последнем обновлении. Попробуйте «Обновить» позже."}
                </p>
              </div>
            )}
            {/* Account header */}
            <div className="flex flex-col sm:flex-row gap-6 items-start sm:items-center mb-8">
              <div className="shrink-0">
                {account.avatar_url ? (
                  <img
                    src={`/api/accounts/${account.id}/avatar/`}
                    alt={account.username}
                    className="w-20 h-20 rounded-full object-cover border-2 border-zinc-700"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  />
                ) : (
                  <div className="w-20 h-20 rounded-full bg-zinc-800 flex items-center justify-center">
                    <PlatformIcon platform={account.platform} className="w-8 h-8 text-zinc-400" />
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <h1 className="text-xl font-bold">
                      <ExternalProfileAnchor platform={account.platform} username={account.username}>
                        {account.display_name || account.username}
                      </ExternalProfileAnchor>
                    </h1>
                    <p className="text-zinc-400 text-sm">
                      <ExternalProfileAnchor platform={account.platform} username={account.username}>
                        {displayHandle(account.platform, account.username)}
                      </ExternalProfileAnchor>
                    </p>
                    <div className="mt-1.5">
                      <ProfileSelector
                        account={account}
                        profiles={profiles}
                        isPending={profileMutation.isPending}
                        onSelect={(id) => profileMutation.mutate(id)}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        if (refreshMutation.isPending) return;
                        refreshMutation.mutate();
                      }}
                      disabled={refreshMutation.isPending}
                      className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-500 px-3 py-1.5 rounded-xl transition-colors disabled:opacity-40"
                    >
                      <RefreshIcon spinning={refreshMutation.isPending} />
                      {refreshMutation.isPending ? "Обновляю…" : "Обновить"}
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Удалить ${displayHandle(account.platform, account.username)}?`)) deleteMutation.mutate();
                      }}
                      disabled={deleteMutation.isPending}
                      className="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-red-400 border border-zinc-800 hover:border-red-900 px-3 py-1.5 rounded-xl transition-colors disabled:opacity-40"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                      Удалить
                    </button>
                  </div>
                </div>
                {account.bio && (
                  <p className="text-zinc-400 text-sm mt-2 line-clamp-2">{account.bio}</p>
                )}
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
              <StatCard
                label="Подписчики"
                value={fmt(account.follower_count)}
                delta={account.follower_delta}
                accent
                show
              />
              <StatCard
                label="Просмотры"
                value={fmt(account.view_count)}
                delta={account.view_delta}
                show={platformStats.views}
              />
              <StatCard
                label="Лайки"
                value={fmt(account.like_count)}
                delta={account.like_delta}
                show={platformStats.likes}
              />
              <StatCard
                label="Публикации"
                value={fmt(account.post_count)}
                delta={account.post_delta}
                show={platformStats.posts}
              />
            </div>

            {refreshMutation.isError && (
              <p className="text-red-400 text-sm mb-4">
                {(refreshMutation.error as any)?.response?.data?.detail || "Ошибка обновления"}
              </p>
            )}

            {/* Tabs */}
            <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 w-fit mb-6">
              {(["posts", "analytics"] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    tab === t ? "bg-white text-black" : "text-zinc-400 hover:text-white"
                  }`}
                >
                  {t === "posts" ? `Публикации${posts.length > 0 ? ` (${posts.length})` : ""}` : "Аналитика"}
                </button>
              ))}
            </div>

            {/* Posts tab */}
            {tab === "posts" && (
              <>
                {postsLoading && (
                  <div className="flex justify-center py-12">
                    <div className="w-6 h-6 border-2 border-zinc-600 border-t-transparent rounded-full animate-spin" />
                  </div>
                )}

                {!postsLoading && posts.length === 0 && (
                  <div className="border border-dashed border-zinc-800 rounded-xl py-12 px-6 text-center">
                    {account.post_count > 0 ? (
                      <p className="text-zinc-500 text-sm">
                        Счетчик показывает {account.post_count} публикаций, но платформа не отдала список постов
                        (часто из-за антибота/ограничений). Нажмите «Обновить», когда окно TikTok открыто и проверка пройдена.
                      </p>
                    ) : (
                      <p className="text-zinc-500 text-sm">
                        Публикации появятся после первого обновления аккаунта.
                      </p>
                    )}
                    <button
                      onClick={() => {
                        if (refreshMutation.isPending) return;
                        refreshMutation.mutate();
                      }}
                      disabled={refreshMutation.isPending}
                      className="mt-4 text-sm text-[#fe2c55] hover:text-[#e0254a] disabled:opacity-40"
                    >
                      Обновить сейчас
                    </button>
                  </div>
                )}

                {posts.length > 0 && (
                  <div className={`grid gap-3 ${
                    account.platform === "tiktok"
                      ? "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5"
                      : "grid-cols-1 sm:grid-cols-2 md:grid-cols-3"
                  }`}>
                    {posts.map((post) => (
                      <PostCard key={post.id} post={post} platform={account.platform} />
                    ))}
                  </div>
                )}
              </>
            )}

            {/* Analytics tab */}
            {tab === "analytics" && <Analytics accountId={accountId} />}
          </>
        )}
      </main>
    </div>
  );
}

// ── Profile selector ──────────────────────────────────────────────────────────

function ProfileSelector({
  account,
  profiles,
  isPending,
  onSelect,
}: {
  account: Account;
  profiles: Profile[];
  isPending: boolean;
  onSelect: (profileId: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const current = profiles.find((p) => p.id === account.profile_id);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={isPending}
        className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition-colors disabled:opacity-40 group"
      >
        {isPending ? (
          <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
        ) : current ? (
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: current.color }}
          />
        ) : (
          <svg className="w-3 h-3 text-zinc-600" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        )}
        <span className={current ? "text-zinc-300" : "text-zinc-600"}>
          {current ? current.name : "Без профиля"}
        </span>
        <svg
          className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl z-30 min-w-[200px] py-1 overflow-hidden">
          {/* Remove from profile */}
          <button
            onClick={() => { onSelect(null); setOpen(false); }}
            className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors hover:bg-zinc-800 ${
              account.profile_id === null ? "text-white font-medium" : "text-zinc-500"
            }`}
          >
            <svg className="w-3.5 h-3.5 shrink-0 text-zinc-600" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
            Без профиля
            {account.profile_id === null && (
              <svg className="w-3 h-3 ml-auto text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>

          {profiles.length > 0 && <div className="h-px bg-zinc-800 my-1" />}

          {profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p.id); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors hover:bg-zinc-800 ${
                p.id === account.profile_id ? "text-white font-medium" : "text-zinc-300"
              }`}
            >
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ background: p.color }}
              />
              <span className="flex-1 truncate">{p.name}</span>
              {p.id === account.profile_id && (
                <svg className="w-3 h-3 ml-auto shrink-0 text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              )}
            </button>
          ))}

          {profiles.length === 0 && (
            <p className="px-3 py-2 text-xs text-zinc-600">Профили не созданы</p>
          )}
        </div>
      )}
    </div>
  );
}

function PostCard({ post, platform }: { post: Post; platform: string }) {
  const aspect = THUMB_ASPECT[platform] ?? "aspect-video";
  const hasThumbnail = !!post.thumbnail_url;

  return (
    <a
      href={post.post_url || "#"}
      target="_blank"
      rel="noopener noreferrer"
      className="group bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden hover:border-zinc-600 transition-colors flex flex-col"
    >
      {/* Thumbnail / placeholder */}
      <div className={`${aspect} relative overflow-hidden bg-zinc-800 shrink-0`}>
        {hasThumbnail ? (
          <img
            src={post.thumbnail_url}
            alt=""
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-700">
            <PlatformIcon platform={platform} className="w-8 h-8" />
          </div>
        )}
        {/* View count overlay */}
        {post.view_count > 0 && (
          <div className="absolute bottom-1 left-1 right-1 flex items-center gap-1 text-xs text-white bg-black/60 rounded px-1.5 py-0.5">
            <svg className="w-3 h-3 shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
              <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd" />
            </svg>
            <span className="font-medium">{fmt(post.view_count)}</span>
            <Delta value={post.view_delta} />
          </div>
        )}
      </div>

      {/* Description + stats */}
      <div className="p-2 flex flex-col gap-1.5 flex-1">
        {post.description && (
          <p className="text-zinc-400 text-xs line-clamp-2 leading-relaxed">{post.description}</p>
        )}
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-zinc-500 mt-auto">
          {post.view_count > 0 && hasThumbnail === false && (
            <span className="flex items-center gap-0.5">
              <span>👁</span>
              <span className="text-zinc-300">{fmt(post.view_count)}</span>
              <Delta value={post.view_delta} />
            </span>
          )}
          {post.like_count > 0 && (
            <span className="flex items-center gap-0.5">
              <span>❤️</span>
              <span className="text-zinc-300">{fmt(post.like_count)}</span>
              <Delta value={post.like_delta} />
            </span>
          )}
          {post.comment_count > 0 && (
            <span className="flex items-center gap-0.5">
              <span>💬</span>
              <span className="text-zinc-300">{fmt(post.comment_count)}</span>
              <Delta value={post.comment_delta} />
            </span>
          )}
          {post.share_count > 0 && (
            <span className="flex items-center gap-0.5">
              <span>↗</span>
              <span className="text-zinc-300">{fmt(post.share_count)}</span>
            </span>
          )}
          {post.posted_at && (
            <span className="text-zinc-600 ml-auto">
              {new Date(post.posted_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}
            </span>
          )}
        </div>
      </div>
    </a>
  );
}

function StatCard({
  label,
  value,
  delta,
  accent = false,
  show = true,
}: {
  label: string;
  value: string;
  delta: number | null;
  accent?: boolean;
  show?: boolean;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-4 text-center">
      <p className={`text-2xl font-bold ${show ? (accent ? "text-[#fe2c55]" : "text-white") : "text-zinc-700"}`}>
        {show ? value : "—"}
      </p>
      {show && delta != null && delta !== 0 && (
        <p className={`text-xs font-medium mt-0.5 ${delta > 0 ? "text-green-400" : "text-red-400"}`}>
          {fmtDelta(delta)} за сутки
        </p>
      )}
      <p className="text-zinc-500 text-xs mt-1">{label}</p>
    </div>
  );
}

function RefreshIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg
      className={`w-4 h-4 ${spinning ? "animate-spin" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
      />
    </svg>
  );
}
