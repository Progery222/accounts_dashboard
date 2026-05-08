import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAuthStatus,
  getJobStatus,
  startTikTokAuth,      importTikTokCookies,
  startInstagramAuth,   importInstagramCookies,
  startTelegramAuth,
  startXAuth,           importXCookies,
  startThreadsAuth,     importThreadsCookies,
  startFacebookAuth,    importFacebookCookies,
  startRumbleAuth,      importRumbleCookies,
  startRedditAuth,      importRedditCookies,
  logoutPlatform,
  type AuthPlatform,
  type TikTokStatus,
  type InstagramStatus,
  type TelegramStatus,
  type XStatus,
  type ThreadsStatus,
  type FacebookStatus,
  type RumbleStatus,
  type RedditStatus,
} from "../api/settings";

// ── helpers ───────────────────────────────────────────────────────────────────

/** Days until an "expires" string (e.g. "2026-05-02 12:18 UTC") */
function daysUntil(expires: string | null): number | null {
  if (!expires) return null;
  const d = new Date(expires.replace(" UTC", "Z"));
  const diff = (d.getTime() - Date.now()) / 86_400_000;
  return Math.round(diff);
}

function ExpiryBadge({ expires, name }: { expires: string | null; name: string | null }) {
  const days = daysUntil(expires);
  if (days === null) return <span className="text-zinc-500 text-sm">нет данных</span>;

  const color =
    days <= 7  ? "text-red-400 bg-red-400/10 border-red-400/30" :
    days <= 30 ? "text-amber-400 bg-amber-400/10 border-amber-400/30" :
                 "text-emerald-400 bg-emerald-400/10 border-emerald-400/30";

  const label =
    days <= 0 ? "истёк" :
    days === 1 ? "1 день" :
    days < 30  ? `${days} дн.` :
    days < 365 ? `${Math.round(days / 30)} мес.` :
                 `${(days / 365).toFixed(1)} г.`;

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full border ${color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
      {name && <span className="text-xs opacity-60">· {name}</span>}
    </span>
  );
}

// ── Auth flow hook ────────────────────────────────────────────────────────────

type AuthState = "idle" | "pending" | "done" | "error";

function useAuthFlow(startFn: () => Promise<{ job_id: string }>) {
  const [state, setState] = useState<AuthState>("idle");
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qc = useQueryClient();

  const stop = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const start = async () => {
    setState("pending");
    setMessage("Запуск…");
    try {
      const { job_id } = await startFn();
      setJobId(job_id);
      pollRef.current = setInterval(async () => {
        try {
          const job = await getJobStatus(job_id);
          setMessage(job.message);
          if (job.status === "done") {
            setState("done");
            stop();
            qc.invalidateQueries({ queryKey: ["auth-status"] });
          } else if (job.status === "error") {
            setState("error");
            stop();
          }
        } catch {
          // ignore transient network errors
        }
      }, 1500);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setState("error");
      setMessage(`Не удалось запустить: ${msg}`);
    }
  };

  useEffect(() => () => stop(), []);

  const reset = () => { setState("idle"); setMessage(""); setJobId(null); };

  return { state, message, start, reset, jobId };
}

function SessionLogoutRow({ platform }: { platform: AuthPlatform }) {
  const qc = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const logout = useMutation({
    mutationFn: () => logoutPlatform(platform),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auth-status"] });
      setConfirmOpen(false);
      logout.reset();
    },
  });

  const apiDetail = (() => {
    const e = logout.error;
    if (!e) return "";
    if (isAxiosError(e) && e.response?.data && typeof (e.response.data as { detail?: unknown }).detail === "string") {
      return (e.response.data as { detail: string }).detail;
    }
    return e instanceof Error ? e.message : "";
  })();

  const openDialog = () => {
    logout.reset();
    setConfirmOpen(true);
  };

  return (
    <>
      <div className="mt-3 pt-3 border-t border-zinc-800/80">
        <div className="flex justify-end">
          <button
            type="button"
            disabled={logout.isPending}
            onClick={openDialog}
            className="text-sm text-zinc-400 hover:text-red-400 disabled:opacity-50 transition-colors"
          >
            Завершить сессию
          </button>
        </div>
        {logout.isError && apiDetail && !confirmOpen && (
          <p className="text-red-400 text-xs mt-2 text-right">{apiDetail}</p>
        )}
      </div>

      {confirmOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`logout-title-${platform}`}
        >
          <button
            type="button"
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            aria-label="Закрыть"
            disabled={logout.isPending}
            onClick={() => !logout.isPending && setConfirmOpen(false)}
          />
          <div className="relative w-full max-w-md rounded-2xl border border-zinc-700 bg-zinc-900 p-6 shadow-2xl">
            <h3 id={`logout-title-${platform}`} className="text-lg font-semibold text-white">
              Завершить сессию?
            </h3>
            <p className="mt-3 text-sm text-zinc-400 leading-relaxed">
              Сохранённые данные входа для этой платформы будут удалены. До повторной авторизации скрапинг не сможет
              использовать текущий аккаунт.
            </p>
            {logout.isError && apiDetail && (
              <p className="mt-3 text-sm text-red-400">{apiDetail}</p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                disabled={logout.isPending}
                onClick={() => setConfirmOpen(false)}
                className="rounded-xl border border-zinc-600 px-4 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-800 disabled:opacity-50 transition-colors"
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={logout.isPending}
                onClick={() => logout.mutate()}
                className="rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50 transition-colors"
              >
                {logout.isPending ? "Выход…" : "Завершить"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Platform card ─────────────────────────────────────────────────────────────

function PlatformCard({
  icon,
  title,
  color,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  color: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${color}`}>
          {icon}
        </div>
        <h2 className="text-white font-semibold text-lg">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function AuthButton({
  state,
  message,
  idleLabel,
  onStart,
  onReset,
}: {
  state: AuthState;
  message: string;
  idleLabel: string;
  onStart: () => void;
  onReset: () => void;
}) {
  if (state === "idle") {
    return (
      <button
        onClick={onStart}
        className="flex items-center gap-2 bg-white text-black text-sm font-semibold px-4 py-2 rounded-xl hover:bg-zinc-100 transition-colors"
      >
        {idleLabel}
      </button>
    );
  }

  if (state === "pending") {
    return (
      <div className="flex items-center gap-3">
        <svg className="w-4 h-4 text-zinc-400 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
        </svg>
        <span className="text-zinc-300 text-sm">{message}</span>
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          {message}
        </div>
        <button onClick={onReset} className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors">
          Войти снова
        </button>
      </div>
    );
  }

  // error
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-red-400 text-sm">
        <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
        {message}
      </div>
      <button onClick={onReset} className="text-zinc-400 hover:text-white text-xs transition-colors underline underline-offset-2">
        Попробовать снова
      </button>
    </div>
  );
}

// ── Generic cookie import form ────────────────────────────────────────────────

function CookieImportSection({
  importFn,
  siteDomain,
  primaryCookieName,
}: {
  importFn: (cookies: string) => Promise<{ job_id: string }>;
  siteDomain: string;            // e.g. "tiktok.com"
  primaryCookieName: string;     // e.g. "sessionid" or "auth_token"
}) {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState("");
  const flow = useAuthFlow(() => importFn(raw));

  const handleReset = () => { flow.reset(); setRaw(""); setOpen(false); };

  if (!open && flow.state === "idle") {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors underline underline-offset-2 mt-2"
      >
        Вставить куки вручную (если вход в браузере недоступен)
      </button>
    );
  }

  return (
    <div className="mt-4 space-y-3 border border-zinc-700/60 rounded-xl p-4 bg-zinc-800/40">
      <div className="flex items-start justify-between gap-2">
        <p className="text-zinc-300 text-xs font-medium">Импорт куков из Chrome</p>
        {flow.state === "idle" && (
          <button onClick={() => setOpen(false)} className="text-zinc-600 hover:text-zinc-400">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <ol className="text-zinc-500 text-xs space-y-1 list-decimal list-inside leading-relaxed">
        <li>
          Установите расширение{" "}
          <a href="https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm"
            target="_blank" rel="noreferrer"
            className="text-sky-400 hover:text-sky-300 underline underline-offset-2">
            Cookie-Editor
          </a>{" "}
          в Chrome
        </li>
        <li>
          Откройте <span className="text-zinc-300">{siteDomain}</span> и убедитесь что вы залогинены
        </li>
        <li>
          Кликните на иконку Cookie-Editor → <span className="text-zinc-300">Export → Export All</span>
        </li>
        <li>Вставьте скопированный JSON сюда и нажмите «Импортировать»</li>
      </ol>
      <p className="text-zinc-600 text-xs">
        Или вставьте только значение cookie{" "}
        <span className="text-zinc-400 font-mono">{primaryCookieName}</span>{" "}
        (DevTools → Application → Cookies → {siteDomain}).
      </p>

      {flow.state === "idle" && (
        <>
          <textarea
            value={raw}
            onChange={e => setRaw(e.target.value)}
            placeholder={`[{"name":"${primaryCookieName}","value":"...","domain":".${siteDomain}",...}]`}
            rows={5}
            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-zinc-300 text-xs font-mono resize-y focus:outline-none focus:border-zinc-500 placeholder-zinc-700"
          />
          <button
            onClick={flow.start}
            disabled={!raw.trim()}
            className="flex items-center gap-2 bg-white text-black text-sm font-semibold px-4 py-1.5 rounded-xl hover:bg-zinc-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Импортировать
          </button>
        </>
      )}

      {flow.state === "pending" && (
        <div className="flex items-center gap-2 text-zinc-400 text-sm">
          <svg className="w-4 h-4 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
          {flow.message}
        </div>
      )}

      {flow.state === "done" && (
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            {flow.message}
          </div>
          <button onClick={handleReset} className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors">
            Закрыть
          </button>
        </div>
      )}

      {flow.state === "error" && (
        <div className="space-y-2">
          <div className="flex items-start gap-2 text-red-400 text-sm">
            <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            {flow.message}
          </div>
          <button onClick={handleReset} className="text-zinc-400 hover:text-white text-xs underline underline-offset-2 transition-colors">
            Попробовать снова
          </button>
        </div>
      )}
    </div>
  );
}

// ── TikTok section ────────────────────────────────────────────────────────────

function TikTokSection({ data }: { data: TikTokStatus }) {
  const flow = useAuthFlow(startTikTokAuth);
  const days = daysUntil(data.min_expires);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
          <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01a6.27 6.27 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.33-6.34V8.69a8.18 8.18 0 004.78 1.52V6.75a4.85 4.85 0 01-1.01-.06z" />
        </svg>
      }
      title="TikTok"
      color="bg-black border border-zinc-700"
    >
      {/* Status row */}
      <div className="flex items-center justify-between mb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
            <span className="text-zinc-300 text-sm">
              {data.has_session ? "Авторизован (sessionid активен)" : "Не авторизован"}
            </span>
          </div>
          {data.has_session && data.min_expires && (
            <div className="flex items-center gap-2 pl-4">
              <span className="text-zinc-500 text-xs">Ближайший срок истечения:</span>
              <ExpiryBadge expires={data.min_expires} name={data.min_expires_name} />
            </div>
          )}
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="tiktok" />}

      {/* Warning if expiring soon */}
      {data.has_session && days !== null && days <= 10 && (
        <div className="mb-4 flex items-start gap-2 bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-2.5">
          <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <span className="text-amber-300 text-xs">
            Cookies скоро истекут — обновите авторизацию, чтобы скрапинг продолжал работать.
          </span>
        </div>
      )}

      {/* Primary action: open browser login */}
      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в TikTok"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — войдите в TikTok (если потребуется CAPTCHA, пройдите её).
          Окно закроется автоматически.
        </p>
      )}

      {/* Alternative: paste cookies */}
      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importTikTokCookies}
          siteDomain="tiktok.com"
          primaryCookieName="sessionid"
        />
      )}
    </PlatformCard>
  );
}

// ── Instagram section ─────────────────────────────────────────────────────────

function InstagramSection({ data }: { data: InstagramStatus }) {
  const flow = useAuthFlow(startInstagramAuth);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none">
          <defs>
            <linearGradient id="ig-grad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#f09433" />
              <stop offset="25%" stopColor="#e6683c" />
              <stop offset="50%" stopColor="#dc2743" />
              <stop offset="75%" stopColor="#cc2366" />
              <stop offset="100%" stopColor="#bc1888" />
            </linearGradient>
          </defs>
          <rect x="2" y="2" width="20" height="20" rx="5" stroke="url(#ig-grad)" strokeWidth="2" />
          <circle cx="12" cy="12" r="4" stroke="url(#ig-grad)" strokeWidth="2" />
          <circle cx="17.5" cy="6.5" r="1" fill="url(#ig-grad)" />
        </svg>
      }
      title="Instagram"
      color="bg-zinc-800"
    >
      {/* Status row */}
      <div className="flex items-center justify-between mb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
            <span className="text-zinc-300 text-sm">
              {data.has_session ? "Сессия активна" : "Сессия не создана"}
            </span>
          </div>
          {data.has_session && data.last_updated && (
            <div className="pl-4">
              <span className="text-zinc-500 text-xs">Обновлена: {data.last_updated}</span>
            </div>
          )}
          {data.username && (
            <div className="pl-4">
              <span className="text-zinc-500 text-xs">Аккаунт: @{data.username}</span>
            </div>
          )}
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="instagram" />}

      {/* Action */}
      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Instagram"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — войдите в Instagram. Сессия сохранится автоматически.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importInstagramCookies}
          siteDomain="instagram.com"
          primaryCookieName="sessionid"
        />
      )}
    </PlatformCard>
  );
}

// ── Telegram section ──────────────────────────────────────────────────────────

function TelegramSection({ data }: { data: TelegramStatus }) {
  const flow = useAuthFlow(startTelegramAuth);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
          <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2zm4.93 6.708l-1.707 8.04c-.127.578-.46.718-.932.447l-2.58-1.9-1.244 1.197c-.138.138-.253.253-.52.253l.185-2.625 4.78-4.317c.208-.184-.045-.287-.322-.103l-5.906 3.717-2.546-.795c-.553-.173-.563-.553.115-.818l9.938-3.831c.46-.166.862.113.74.735z" />
        </svg>
      }
      title="Telegram"
      color="bg-sky-500/20 border border-sky-500/30"
    >
      {/* Status row */}
      <div className="flex items-center justify-between mb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
            <span className="text-zinc-300 text-sm">
              {data.has_session
                ? "Сессия Telegram обнаружена"
                : data.profile_exists
                  ? "Профиль есть, но сессия Telegram не найдена"
                  : "Сессия не создана"}
            </span>
          </div>
          {data.has_session && (
            <div className="pl-4">
              <span className="text-zinc-500 text-xs">
                Данные хранятся в браузерном профиле приложения
              </span>
            </div>
          )}
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="telegram" />}

      {/* Action */}
      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Telegram"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется Telegram Web в браузере — войдите в аккаунт (QR-код или номер телефона).
          Окно закроется автоматически после входа.
        </p>
      )}
    </PlatformCard>
  );
}

// ── X (Twitter) section ───────────────────────────────────────────────────────

function XSection({ data }: { data: XStatus }) {
  const flow = useAuthFlow(startXAuth);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.748l7.73-8.835L1.254 2.25H8.08l4.253 5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
        </svg>
      }
      title="X (Twitter)"
      color="bg-zinc-950 border border-zinc-700"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
          <span className="text-zinc-300 text-sm">
            {data.has_session ? "Сессия X обнаружена" : "Сессия не создана"}
          </span>
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="x" />}

      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в X"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — войдите в свой аккаунт X. Окно закроется автоматически.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importXCookies}
          siteDomain="x.com"
          primaryCookieName="auth_token"
        />
      )}
    </PlatformCard>
  );
}

// ── Threads section ───────────────────────────────────────────────────────────

function ThreadsSection({ data }: { data: ThreadsStatus }) {
  const flow = useAuthFlow(startThreadsAuth);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
          <path d="M19.59 12.27c-.16-2.85-1.72-4.5-4.34-4.52h-.03c-1.57 0-2.88.67-3.68 1.89l1.44.99c.6-.91 1.54-1.1 2.24-1.1h.02c.86.01 1.52.26 1.94.75.31.36.51.85.61 1.47-.77-.13-1.59-.17-2.48-.12-2.49.14-4.1 1.6-3.99 3.62.05 1.03.57 1.91 1.44 2.49.73.49 1.67.73 2.65.67 1.29-.07 2.31-.57 3.02-1.47.53-.68.87-1.56 1.01-2.67.61.37 1.06.84 1.31 1.39.45 1.02.48 2.71-.94 4.13-1.26 1.26-2.79 1.8-5.07 1.82-2.55-.18-4.47-.84-5.72-2.44-1.17-1.51-1.77-3.68-1.8-6.47.03-2.79.63-4.97 1.8-6.47 1.25-1.6 3.17-2.25 5.72-2.43 2.57.18 4.51.84 5.79 2.45.62.79 1.1 1.77 1.4 2.91l1.69-.45c-.36-1.36-.95-2.54-1.75-3.51C18.15 2.03 15.71.89 12.18.7h-.04C8.6.89 6.16 2.04 4.59 4.01c-1.44 1.83-2.18 4.47-2.2 7.97v.02c.02 3.5.76 6.14 2.2 7.97 1.57 1.97 4.01 3.12 7.55 3.31h.04c3.12-.17 5.08-.91 6.93-2.74 2.34-2.34 2.27-5.28 1.5-7.07a5.34 5.34 0 00-2.01-2.18l-.01-.02zm-7.4 4.12c-1.09.06-2.23-.43-2.29-1.49-.04-.8.57-1.7 2.43-1.8.21-.01.42-.02.62-.02.65 0 1.26.06 1.81.18-.21 2.57-1.53 3.06-2.57 3.13z" />
        </svg>
      }
      title="Threads"
      color="bg-zinc-800"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
          <span className="text-zinc-300 text-sm">
            {data.has_session ? "Сессия Threads обнаружена" : "Сессия не создана"}
          </span>
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="threads" />}

      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Threads"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — войдите через аккаунт Instagram. Окно закроется автоматически.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importThreadsCookies}
          siteDomain="threads.net"
          primaryCookieName="sessionid"
        />
      )}
    </PlatformCard>
  );
}

// ── Facebook section ──────────────────────────────────────────────────────────

function FacebookSection({ data }: { data: FacebookStatus }) {
  const flow = useAuthFlow(startFacebookAuth);

  return (
    <PlatformCard
      icon={
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
          <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047v-2.66c0-3.025 1.791-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.887v2.264h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z" />
        </svg>
      }
      title="Facebook"
      color="bg-[#1877F2]/20 border border-[#1877F2]/30"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
            <span className="text-zinc-300 text-sm">
              {data.has_session ? "Сессия Facebook обнаружена" : "Сессия не создана"}
            </span>
          </div>
          {data.has_session && (
            <div className="pl-4">
              <span className="text-zinc-500 text-xs">
                Данные хранятся в браузерном профиле приложения
              </span>
            </div>
          )}
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="facebook" />}

      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Facebook"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — данные для входа заполнятся автоматически.
          Если появится капча или двухфакторная проверка — пройдите её вручную.
          Окно закроется после успешного входа.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importFacebookCookies}
          siteDomain="facebook.com"
          primaryCookieName="c_user"
        />
      )}
    </PlatformCard>
  );
}

function RumbleSection({ data }: { data: RumbleStatus }) {
  const flow = useAuthFlow(startRumbleAuth);

  return (
    <PlatformCard
      icon={<span className="text-white font-bold text-sm">R</span>}
      title="Rumble"
      color="bg-emerald-500/20 border border-emerald-500/30"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
          <span className="text-zinc-300 text-sm">
            {data.has_session ? "Сессия Rumble обнаружена" : "Сессия не создана"}
          </span>
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="rumble" />}

      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Rumble"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — пройдите проверку/вход на Rumble. Окно закроется автоматически.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importRumbleCookies}
          siteDomain="rumble.com"
          primaryCookieName="cf_clearance"
        />
      )}
    </PlatformCard>
  );
}

function RedditSection({ data }: { data: RedditStatus }) {
  const flow = useAuthFlow(startRedditAuth);

  return (
    <PlatformCard
      icon={<span className="text-white font-bold text-sm">r/</span>}
      title="Reddit"
      color="bg-orange-500/20 border border-orange-500/30"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${data.has_session ? "bg-emerald-400" : "bg-zinc-600"}`} />
          <span className="text-zinc-300 text-sm">
            {data.has_session ? "Сессия Reddit обнаружена" : "Сессия не создана"}
          </span>
        </div>
      </div>

      {data.has_session && <SessionLogoutRow platform="reddit" />}

      <AuthButton
        state={flow.state}
        message={flow.message}
        idleLabel={data.has_session ? "Обновить авторизацию" : "Войти в Reddit"}
        onStart={flow.start}
        onReset={flow.reset}
      />

      {flow.state === "pending" && (
        <p className="mt-3 text-zinc-500 text-xs leading-relaxed max-w-sm">
          Откроется окно браузера — войдите в Reddit. Окно закроется автоматически.
        </p>
      )}

      {flow.state === "idle" && (
        <CookieImportSection
          importFn={importRedditCookies}
          siteDomain="reddit.com"
          primaryCookieName="reddit_session"
        />
      )}
    </PlatformCard>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["auth-status"],
    queryFn: getAuthStatus,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-black/90 backdrop-blur border-b border-zinc-800 px-4 py-3">
        <div className="max-w-3xl mx-auto flex items-center gap-4">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-1.5 text-zinc-400 hover:text-white text-sm transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Назад
          </button>
          <span className="text-white font-semibold">Настройки авторизации</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-4">
        {/* Intro */}
        <p className="text-zinc-400 text-sm leading-relaxed">
          Для сбора данных приложение использует авторизованные сессии в браузере.
          Нажмите кнопку — откроется окно, войдите в аккаунт, и данные будут обновляться автоматически.
        </p>

        {isLoading && (
          <div className="flex items-center gap-2 text-zinc-500 py-8">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            Загрузка…
          </div>
        )}

        {error && (
          <div className="text-red-400 text-sm">
            Не удалось загрузить статус авторизации.
          </div>
        )}

        {data && (
          <div className="space-y-4">
            <TikTokSection    data={data.tiktok}    />
            <InstagramSection data={data.instagram} />
            <TelegramSection  data={data.telegram}  />
            <XSection         data={data.x}         />
            <ThreadsSection   data={data.threads}   />
            <FacebookSection  data={data.facebook}  />
            <RumbleSection    data={data.rumble}    />
            <RedditSection    data={data.reddit}    />
          </div>
        )}
      </main>
    </div>
  );
}
