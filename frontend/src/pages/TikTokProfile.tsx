import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchTikTokProfile } from "../platforms/tiktok";
import { createAccount } from "../api/accounts";
import VideoCard from "../components/VideoCard";

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

export default function TikTokProfile() {
  const { username = "" } = useParams<{ username: string }>();

  const qc = useQueryClient();
  const [saved, setSaved] = useState(false);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tiktok", username],
    queryFn: () => fetchTikTokProfile(username),
    enabled: !!username,
  });

  const saveMutation = useMutation({
    mutationFn: () => createAccount({
      username: data!.username,
      platform: "tiktok",
      display_name: data!.nickname,
      avatar_url: data!.avatar,
      bio: data!.bio,
      follower_count: data!.follower_count,
      like_count: data!.like_count,
      post_count: data!.video_count,
    }),
    onSuccess: () => { setSaved(true); qc.invalidateQueries({ queryKey: ["accounts"] }); },
  });

  return (
    <div className="min-h-screen bg-black text-white">
      <header className="sticky top-0 z-10 bg-black/80 backdrop-blur border-b border-zinc-800 px-4 py-3">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link
            to="/accounts"
            className="text-zinc-400 hover:text-white transition-colors flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            <span className="text-sm">Аккаунты</span>
          </Link>
          <span className="text-zinc-600">/</span>
          <span className="text-zinc-300 font-medium">@{username}</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {isLoading && (
          <div className="flex flex-col items-center justify-center py-32 gap-4">
            <div className="w-10 h-10 border-2 border-[#fe2c55] border-t-transparent rounded-full animate-spin" />
            <p className="text-zinc-400">Загружаем @{username}…</p>
            <p className="text-zinc-600 text-xs">Открываем браузер для получения видео, ~20 сек</p>
          </div>
        )}

        {isError && (
          <div className="flex flex-col items-center justify-center py-32 gap-4 text-center">
            <div className="w-16 h-16 rounded-full bg-zinc-900 flex items-center justify-center text-2xl">⚠️</div>
            <p className="text-zinc-300 text-lg font-medium">Не удалось загрузить профиль</p>
            <p className="text-zinc-500 text-sm max-w-sm">
              {(error as Error)?.message ?? "Проверь имя аккаунта или попробуй позже."}
            </p>
            <Link
              to="/"
              className="mt-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-white px-5 py-2.5 rounded-xl text-sm transition-colors"
            >
              Попробовать снова
            </Link>
          </div>
        )}

        {data && (
          <>
            <div className="flex flex-col sm:flex-row gap-6 items-start sm:items-center mb-10">
              <div className="relative shrink-0">
                <img
                  src={data.avatar}
                  alt={data.nickname}
                  className="w-24 h-24 rounded-full object-cover border-2 border-zinc-700"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                />
                {data.verified && (
                  <span className="absolute -bottom-1 -right-1 bg-[#20d5ec] rounded-full w-6 h-6 flex items-center justify-center">
                    <svg className="w-3.5 h-3.5 text-black" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <h1 className="text-2xl font-bold truncate">{data.nickname}</h1>
                <p className="text-zinc-400 text-sm mb-3">@{data.username}</p>
                {data.bio && (
                  <p className="text-zinc-300 text-sm whitespace-pre-line line-clamp-3">{data.bio}</p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-10">
              <StatCard label="Видео" value={fmt(data.video_count)} />
              <StatCard label="Подписчики" value={fmt(data.follower_count)} accent />
              <StatCard label="Лайки" value={fmt(data.like_count)} />
            </div>

            <div className="flex items-center gap-3 mb-8">
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || saved}
                className={`text-sm font-semibold px-5 py-2 rounded-xl transition-colors border ${
                  saved
                    ? "border-green-700 text-green-400 cursor-default"
                    : "border-zinc-700 text-zinc-300 hover:border-[#fe2c55] hover:text-[#fe2c55]"
                } disabled:opacity-50`}
              >
                {saved ? "✓ Сохранён" : saveMutation.isPending ? "Сохраняю…" : "+ В аккаунты"}
              </button>
              {saveMutation.isError && <span className="text-red-400 text-xs">Уже сохранён</span>}
            </div>

            <div className="mb-6">
              <h2 className="text-lg font-semibold">
                Публикации
                {data.videos.length > 0 && (
                  <span className="ml-2 text-sm text-zinc-500 font-normal">
                    (показано {data.videos.length})
                  </span>
                )}
              </h2>
            </div>

            {data.videos.length === 0 ? (
              <div className="border border-dashed border-zinc-800 rounded-xl py-12 px-6 text-center">
                <p className="text-zinc-400 text-base font-medium mb-2">Видео не загрузились</p>
                <p className="text-zinc-600 text-sm max-w-sm mx-auto">
                  Попробуй обновить страницу. Если профиль приватный — видео недоступны.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {data.videos.map((video) => (
                  <VideoCard key={video.id} video={video} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-4 text-center">
      <p className={`text-2xl font-bold ${accent ? "text-[#fe2c55]" : "text-white"}`}>{value}</p>
      <p className="text-zinc-500 text-xs mt-1">{label}</p>
    </div>
  );
}
