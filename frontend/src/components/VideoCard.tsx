import type { TikTokVideo } from "../platforms/tiktok";

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
        <div className="absolute bottom-2 left-2 flex items-center gap-1 text-white text-sm font-semibold">
          <EyeIcon className="w-4 h-4" />
          <span>{fmt(video.play_count)}</span>
        </div>
      </div>

      <div className="p-3">
        {video.description && (
          <p className="text-zinc-300 text-sm line-clamp-2 mb-2">{video.description}</p>
        )}
        <div className="flex items-center justify-between text-xs text-zinc-500">
          <div className="flex gap-3">
            <Stat icon={<HeartIcon />} value={fmt(video.like_count)} />
            <Stat icon={<CommentIcon />} value={fmt(video.comment_count)} />
            <Stat icon={<ShareIcon />} value={fmt(video.share_count)} />
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

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg fill="currentColor" viewBox="0 0 20 20" className={className ?? "w-full h-full"}>
      <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
      <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd" />
    </svg>
  );
}

function HeartIcon() {
  return (
    <svg fill="currentColor" viewBox="0 0 20 20" className="w-full h-full">
      <path fillRule="evenodd" d="M3.172 5.172a4 4 0 015.656 0L10 6.343l1.172-1.171a4 4 0 115.656 5.656L10 17.657l-6.828-6.829a4 4 0 010-5.656z" clipRule="evenodd" />
    </svg>
  );
}

function CommentIcon() {
  return (
    <svg fill="currentColor" viewBox="0 0 20 20" className="w-full h-full">
      <path fillRule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clipRule="evenodd" />
    </svg>
  );
}

function ShareIcon() {
  return (
    <svg fill="currentColor" viewBox="0 0 20 20" className="w-full h-full">
      <path d="M15 8a3 3 0 10-2.977-2.63l-4.94 2.47a3 3 0 100 4.319l4.94 2.47a3 3 0 10.895-1.789l-4.94-2.47a3.027 3.027 0 000-.74l4.94-2.47C13.456 7.68 14.19 8 15 8z" />
    </svg>
  );
}
