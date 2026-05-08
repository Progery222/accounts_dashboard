import type { TikTokVideo } from "../platforms/tiktok";
import { IconViews, IconLikes, IconComments, IconRepost } from "./postStatIcons";

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function VideoCard({ video }: { video: TikTokVideo }) {
  return (
    <div className="bg-zinc-900 rounded-xl overflow-hidden border border-zinc-800 hover:border-zinc-600 transition-colors group">
      <div className="relative aspect-[9/16] bg-zinc-800">
        {video.cover ? (
          <img
            src={video.cover}
            alt={video.description}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-600">
            <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 20 20">
              <path d="M2 6a2 2 0 012-2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6zm14.553 1.106A1 1 0 0016 8v4a1 1 0 00.553.894l2 1A1 1 0 0020 13V7a1 1 0 00-1.447-.894l-2 1z" />
            </svg>
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />
        <div className="absolute bottom-2 left-2 flex items-center gap-1.5 text-white text-sm font-semibold">
          <IconViews className="w-4 h-4 shrink-0 opacity-95" />
          <span className="tabular-nums">{fmt(video.play_count)}</span>
        </div>
      </div>

      <div className="p-3">
        {video.description && (
          <p className="text-zinc-300 text-sm line-clamp-2 mb-2">{video.description}</p>
        )}
        <div className="flex items-center justify-between text-xs text-zinc-500">
          <div className="flex gap-3">
            <Stat icon={<IconLikes className="w-full h-full text-rose-400/90" />} value={fmt(video.like_count)} />
            <Stat icon={<IconComments className="w-full h-full text-zinc-400" />} value={fmt(video.comment_count)} />
            <Stat icon={<IconRepost className="w-full h-full text-zinc-400" />} value={fmt(video.share_count)} />
          </div>
          {video.created_at > 0 && (
            <span>{formatDate(video.created_at)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ icon, value }: { icon: React.ReactNode; value: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="w-3.5 h-3.5">{icon}</span>
      {value}
    </span>
  );
}

