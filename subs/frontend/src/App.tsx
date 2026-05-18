import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PresumedChartsPanel, type PresumedStatsResponse } from "./csvPresumedCharts";
import {
  SubsBulkRunDetailOverlay,
  type SubsBulkRunDetail,
  type SubsBulkRunItem,
} from "./subsBulkRunDetail";
import {
  SubsMembersPreviewModal,
  type SubsMembersPreviewAccount,
} from "./subsMembersPreviewModal";
import {
  SUBS_AUDIENCE_PLATFORM_LIMITS,
  interleaveAccountsByPlatform,
  runSubsBulkParallelPool,
  subsBulkEffectiveWorkerCount,
} from "./subsBulkParallel";

/** Размер страницы для списка подписчиков (API) и таблицы аккаунтов (клиент). */
const SUBS_LIST_PAGE_SIZE = 10;

/** HTTP только на localhost / 127.0.0.1 — с HTTPS-страницы браузер заблокирует как mixed content («Failed to fetch»). */
function isHttpLoopbackApiBase(base: string): boolean {
  if (!base) return false;
  try {
    const u = new URL(base.includes("://") ? base : `http://${base}`);
    if (u.protocol !== "http:") return false;
    return u.hostname === "localhost" || u.hostname === "127.0.0.1" || u.hostname === "[::1]";
  } catch {
    return false;
  }
}

/** База URL subs API. Через trycloudflare страница HTTPS — запросы только на тот же origin (/api…), Vite проксирует на :8000. */
const subsApi = (): string => {
  const raw = import.meta.env.VITE_API_URL;
  let base: string;
  if (raw !== undefined && String(raw).trim() !== "") {
    base = String(raw).replace(/\/$/, "");
  } else if (import.meta.env.DEV) {
    base = "";
  } else if (typeof window !== "undefined" && window.location.protocol === "https:") {
    base = "";
  } else {
    base = "http://127.0.0.1:8000";
  }
  if (typeof window !== "undefined" && window.location.protocol === "https:" && isHttpLoopbackApiBase(base)) {
    return "";
  }
  return base;
};

const PLATFORMS = [
  { id: "tiktok" as const, label: "TikTok", color: "#ff2d55" },
  { id: "instagram" as const, label: "Instagram", color: "#ec4899" },
  { id: "x" as const, label: "X", color: "#e7e9ea" },
  { id: "threads" as const, label: "Threads", color: "#a8a8a8" },
  { id: "facebook" as const, label: "Facebook", color: "#0866ff" },
] as const;

type SubsPlatformId = (typeof PLATFORMS)[number]["id"];
type SubsPlatformFilter = "all" | SubsPlatformId;

/** Фильтр страницы subs: все / без профиля / один или несколько профилей (объединение на бэкенде). */
type SubsProfileFilter =
  | { kind: "all" }
  | { kind: "none" }
  | { kind: "profiles"; ids: number[] };

function fmtNum(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

type PagerChunk = number | "gap";

/** Номера страниц с пропусками (как в поисковике при большом числе страниц). */
function buildPaginationChunks(current: number, totalPages: number): PagerChunk[] {
  if (totalPages <= 1) return [1];
  if (totalPages <= 12) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const windowSide = 2;
  const left = Math.max(2, current - windowSide);
  const right = Math.min(totalPages - 1, current + windowSide);
  const chunks: PagerChunk[] = [1];
  if (left > 2) chunks.push("gap");
  for (let p = left; p <= right; p += 1) chunks.push(p);
  if (right < totalPages - 1) chunks.push("gap");
  chunks.push(totalPages);
  return chunks;
}

function SubsPagerBar(props: {
  page: number;
  totalPages: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
}) {
  const { page, totalPages, disabled = false, onPageChange } = props;
  if (totalPages <= 1) return null;
  const chunks = buildPaginationChunks(page, totalPages);
  return (
    <div className="subs-pager" role="navigation" aria-label="Нумерация страниц">
      <button
        type="button"
        className="subs-btn subs-btn--sm subs-btn--muted subs-pager-arrow"
        disabled={page <= 1 || disabled}
        aria-label="Предыдущая страница"
        onClick={() => onPageChange(page - 1)}
      >
        ←
      </button>
      <div className="subs-pager-nums">
        {chunks.map((c, i) =>
          c === "gap" ? (
            <span key={`gap-${i}-${page}`} className="subs-pager-gap" aria-hidden>
              …
            </span>
          ) : (
            <button
              key={c}
              type="button"
              className={`subs-pager-page${c === page ? " subs-pager-page--active" : ""}`}
              disabled={disabled || c === page}
              aria-current={c === page ? "page" : undefined}
              aria-label={`Страница ${c}`}
              onClick={() => onPageChange(c)}
            >
              {c}
            </button>
          ),
        )}
      </div>
      <button
        type="button"
        className="subs-btn subs-btn--sm subs-btn--muted subs-pager-arrow"
        disabled={page >= totalPages || disabled}
        aria-label="Следующая страница"
        onClick={() => onPageChange(page + 1)}
      >
        →
      </button>
    </div>
  );
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "—";
  }
}

function profileUrl(platform: string, username: string): string | null {
  const u = String(username || "")
    .replace(/^@+/, "")
    .trim();
  if (!u) return null;
  if (platform === "tiktok") return `https://www.tiktok.com/@${encodeURIComponent(u)}`;
  if (platform === "instagram") return `https://www.instagram.com/${encodeURIComponent(u)}/`;
  if (platform === "x") return `https://x.com/${encodeURIComponent(u)}`;
  if (platform === "threads") return `https://www.threads.net/@${encodeURIComponent(u)}`;
  if (platform === "facebook") return `https://www.facebook.com/${encodeURIComponent(u)}`;
  return null;
}

function subsPlatformLabel(platform: string): string {
  const m = PLATFORMS.find((p) => p.id === platform);
  return m?.label ?? platform;
}

/** Сообщение для сетевых сбоев fetch (прокси Vite :5180 → 127.0.0.1:8000). */
function formatLoadNetworkErr(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  const net =
    msg === "Failed to fetch" ||
    msg === "Load failed" ||
    msg === "NetworkError when attempting to fetch resource.";
  if (!net) return msg;
  return (
    "Не удалось связаться с API. В режиме разработки запросы /api проксируются на http://127.0.0.1:8000 — " +
    "убедитесь, что Django запущен (manage.py runserver 127.0.0.1:8000). " +
    "Если API на другом хосте/порту, задайте VITE_API_URL или target прокси в vite.config.ts."
  );
}

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, { ...init, cache: "no-store" });
  if (res.status === 204) {
    return null;
  }
  const body: unknown = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail?: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

type Overview = {
  summary: {
    tracked_accounts_count: number;
    accounts_with_audience_rows: number;
    accounts_synced_at_least_once: number;
    unique_subscribers_total: number;
    private_subscribers_total: number;
  };
  accounts: Array<{
    id: number;
    dashboard_account_id: number | null;
    platform: string;
    username: string;
    display_name: string;
    audience_count: number;
    audience_last_synced_at: string | null;
    profile_id: number | null;
    profile_name: string | null;
  }>;
};

type MembersResp = {
  count: number;
  page: number;
  page_size: number;
  results: Array<{
    id: number;
    platform: string;
    username: string;
    display_name: string;
    avatar_url?: string;
    bio?: string;
    is_private: boolean;
    follower_count?: number;
    following_count?: number;
    like_count?: number;
    follows_tracked_accounts: number;
  }>;
};

/** Клик по карточке метрик: фильтр/сортировка списков */
type InsightMetricKey = "accounts" | "unique" | "private" | "with_data";

type MemberCardDetail = {
  id: number;
  platform: string;
  username: string;
  external_id: string;
  display_name: string;
  avatar_url: string;
  bio: string;
  is_private: boolean;
  follower_count: number;
  following_count: number;
  like_count: number;
  follows_tracked_accounts: number;
  created_at: string | null;
  updated_at: string | null;
  tracked_accounts: Array<{
    subs_account_id: number;
    dashboard_account_id: number | null;
    username: string;
    platform: string;
    profile_name: string | null;
    last_synced_at: string | null;
  }>;
  /** Те же эвристики, что колонки «Предполагаемый …» в CSV экспорта */
  presumed?: Array<{ label: string; value: string }>;
};

/** Ответ GET …/members/export/last/preview/ */
type CsvLastPreview = {
  generated_at: string | null;
  query_string: string;
  headers: string[];
  rows: string[][];
  row_total: number;
  preview_row_count: number;
  truncated: boolean;
};

/** Оверлей прогресса массового сбора аудитории */
type BulkAudienceProgress = {
  total: number;
  /** 1..total — номер аккаунта в очереди */
  current: number;
  username: string;
  phase: "account" | "pause" | "csv";
};

const SUBS_BULK_LS_KEY = "subs_bulk_collection_v1";
const SUBS_BULK_BC_NAME = "subs-bulk-abort-v1";
/** Синхронизация «Остановить» между вкладками, если BroadcastChannel недоступен. */
const SUBS_BULK_ABORT_STORAGE_KEY = "subs_bulk_abort_broadcast_v1";
/** Как в AccountStats / расписание автообновления: не запускать съём, если аудитория уже снималась недавно. */
const SUBS_BULK_SKIP_RECENT_HOURS = [0, 1, 3, 6, 12, 24] as const;

type BulkModalAudienceSort = "default" | "sync_desc" | "sync_asc";

/** Модалка выбора отслеживаемых аккаунтов: сбор списка или обновление профилей подписчиков. */
type AudiencePickKind = "collect" | "enrich";

function audienceSyncTsMs(iso: string | null): number | null {
  if (!iso) return null;
  const n = Date.parse(iso);
  return Number.isNaN(n) ? null : n;
}

/** true — пропустить аккаунт (не дергать дашборд), если последний съём аудитории был менее `hours` ч назад. */
function isSubsAudienceSyncedWithinHours(lastSyncedIso: string | null, hours: number): boolean {
  if (hours <= 0 || !lastSyncedIso) return false;
  const t = Date.parse(lastSyncedIso);
  if (Number.isNaN(t)) return false;
  return Date.now() - t < hours * 3600 * 1000;
}
/** Если метка давности не обновлялась — считаем, что вкладка сорвала сбор (закрыли). Должно быть заметно больше максимального одного POST (съём аудитории); иначе «зеркальная» вкладка сбросит прогресс во время долгого аккаунта. */
const SUBS_BULK_STALE_MS = 50 * 60 * 1000;

type SubsBulkStored = {
  v: 1;
  running: boolean;
  progress: BulkAudienceProgress | null;
  updatedAt: number;
  runDetail?: SubsBulkRunDetail | null;
};

function isBulkProgressValue(p: unknown): p is BulkAudienceProgress {
  if (!p || typeof p !== "object") return false;
  const o = p as Record<string, unknown>;
  return (
    typeof o.total === "number" &&
    typeof o.current === "number" &&
    typeof o.username === "string" &&
    (o.phase === "account" || o.phase === "pause" || o.phase === "csv")
  );
}

function isSubsBulkRunDetail(v: unknown): v is SubsBulkRunDetail {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  if (!Array.isArray(o.items) || typeof o.worker_count !== "number") return false;
  return o.items.every((it) => {
    if (!it || typeof it !== "object") return false;
    const row = it as Record<string, unknown>;
    return (
      typeof row.account_id === "number" &&
      typeof row.platform === "string" &&
      typeof row.username === "string" &&
      typeof row.status === "string"
    );
  });
}

function patchSubsBulkRunDetail(
  detail: SubsBulkRunDetail,
  accountId: number,
  patch: Partial<SubsBulkRunItem>,
): SubsBulkRunDetail {
  return {
    ...detail,
    items: detail.items.map((it) => (it.account_id === accountId ? { ...it, ...patch } : it)),
  };
}

function finalizeCancelledBulkDetail(detail: SubsBulkRunDetail): SubsBulkRunDetail {
  return {
    ...detail,
    items: detail.items.map((it) => {
      if (it.status !== "queued" && it.status !== "running") return it;
      return {
        ...it,
        status: "cancelled",
        detail: it.status === "running" ? "Остановлено" : it.detail ?? "Не запускался",
        worker: null,
      };
    }),
  };
}

function persistSubsBulkState(progress: BulkAudienceProgress | null, runDetail?: SubsBulkRunDetail | null): void {
  try {
    let mergedDetail: SubsBulkRunDetail | null | undefined = runDetail;
    if (mergedDetail === undefined) {
      try {
        const raw = localStorage.getItem(SUBS_BULK_LS_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as Partial<SubsBulkStored>;
          if (isSubsBulkRunDetail(parsed.runDetail)) mergedDetail = parsed.runDetail;
        }
      } catch {
        /* */
      }
    }
    const payload: SubsBulkStored = {
      v: 1,
      running: true,
      progress,
      updatedAt: Date.now(),
      ...(mergedDetail != null ? { runDetail: mergedDetail } : {}),
    };
    localStorage.setItem(SUBS_BULK_LS_KEY, JSON.stringify(payload));
  } catch {
    /* private / quota */
  }
}

function clearSubsBulkState(): void {
  try {
    localStorage.removeItem(SUBS_BULK_LS_KEY);
  } catch {
    /* */
  }
}

/** Продлевает «свежесть» метки в localStorage во время долгого HTTP (один аккаунт может занимать 10+ мин). */
function bumpSubsBulkLsTimestamp(): void {
  try {
    const raw = localStorage.getItem(SUBS_BULK_LS_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Partial<SubsBulkStored>;
    if (parsed.v !== 1 || !parsed.running) return;
    parsed.updatedAt = Date.now();
    localStorage.setItem(SUBS_BULK_LS_KEY, JSON.stringify(parsed));
  } catch {
    /* */
  }
}

export default function App() {
  const [narrow, setNarrow] = useState(false);
  const [filterPlatform, setFilterPlatform] = useState<SubsPlatformFilter>("all");
  const [profileFilter, setProfileFilter] = useState<SubsProfileFilter>({ kind: "all" });

  const [overview, setOverview] = useState<Overview | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [accountSearch, setAccountSearch] = useState("");
  const [memberSearchInput, setMemberSearchInput] = useState("");
  const [memberSearch, setMemberSearch] = useState("");
  /** id аккаунта в subs: показать справа только подписчиков этого аккаунта */
  const [membersFilterAccountId, setMembersFilterAccountId] = useState<number | null>(null);
  const [memberPage, setMemberPage] = useState(1);
  const [accountTablePage, setAccountTablePage] = useState(1);
  const [insightMetric, setInsightMetric] = useState<InsightMetricKey | null>(null);
  const [membersData, setMembersData] = useState<MembersResp | null>(null);
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersErr, setMembersErr] = useState<string | null>(null);
  const [memberDeleteTarget, setMemberDeleteTarget] = useState<MembersResp["results"][0] | null>(null);
  const [memberDeleteBusy, setMemberDeleteBusy] = useState(false);
  const [memberCardId, setMemberCardId] = useState<number | null>(null);
  const [memberCard, setMemberCard] = useState<MemberCardDetail | null>(null);
  const [memberCardLoading, setMemberCardLoading] = useState(false);
  const [memberCardErr, setMemberCardErr] = useState<string | null>(null);
  /** Раскрытие блока «Предполагаемые данные» в карточке подписчика */
  const [memberCardPresumedOpen, setMemberCardPresumedOpen] = useState(false);

  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkAudienceProgress, setBulkAudienceProgress] = useState<BulkAudienceProgress | null>(null);
  const [singleAudienceUsername, setSingleAudienceUsername] = useState<string | null>(null);
  const [audiencePickOpen, setAudiencePickOpen] = useState(false);
  const [audiencePickKind, setAudiencePickKind] = useState<AudiencePickKind>("collect");
  const [enrichAccountSearch, setEnrichAccountSearch] = useState("");
  const [membersPreviewAccount, setMembersPreviewAccount] = useState<SubsMembersPreviewAccount | null>(null);
  const [bulkSelectedIds, setBulkSelectedIds] = useState<Set<number>>(() => new Set());
  /** Пустой массив = все площадки; иначе аккаунт попадает в список, если platform в наборе. */
  const [bulkModalPlatforms, setBulkModalPlatforms] = useState<string[]>([]);
  /** Пустой массив = все профили; иначе OR по ключам: "none" (без профиля) или "id:123". */
  const [bulkModalProfileKeys, setBulkModalProfileKeys] = useState<string[]>([]);
  const [bulkOperationKind, setBulkOperationKind] = useState<AudiencePickKind>("collect");
  /** Пропуск недавно снятых (по `audience_last_synced_at` в subs), часы — как в автообновлении дашборда. */
  const [bulkSkipRecentHours, setBulkSkipRecentHours] = useState<number>(0);
  /** Порядок строк в модалке массового сбора. */
  const [bulkModalAudienceSort, setBulkModalAudienceSort] = useState<BulkModalAudienceSort>("default");
  /** Не открывать дашборд для аккаунтов без строк подписчиков в БД subs (ускоряет массовый съём). */
  const [bulkSkipZeroSubscribersInDb, setBulkSkipZeroSubscribersInDb] = useState(false);
  /** Прерывание массового сбора (пауза между аккаунтами и активные fetch). */
  const bulkAbortRef = useRef<AbortController | null>(null);
  /** Прерывание одиночного сбора по кнопке в строке аккаунта. */
  const singleAbortRef = useRef<AbortController | null>(null);
  /** Увеличивается при «Остановить» — выходим из цикла даже если fetch не отпускает прокси сразу. */
  const bulkStopGenerationRef = useRef(0);
  /** true только в той вкладке, где выполняется runBulk (не зеркалировать своё же localStorage). */
  const bulkRunActiveInThisTabRef = useRef(false);
  /** Один активный POST съёма аудитории (двойной клик до re-render не шлёт два запроса). */
  const singleAudienceRequestRef = useRef(false);
  const [bulkRemoteView, setBulkRemoteView] = useState(false);
  const [bulkRunDetail, setBulkRunDetail] = useState<SubsBulkRunDetail | null>(null);
  const [bulkRunDetailOpen, setBulkRunDetailOpen] = useState(false);
  const [subsProfiles, setSubsProfiles] = useState<Array<{ id: number; name: string }>>([]);
  const [syncBusy, setSyncBusy] = useState(false);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);
  const [csvPreviewOpen, setCsvPreviewOpen] = useState(false);
  const [csvPreviewLoading, setCsvPreviewLoading] = useState(false);
  const [csvPreviewErr, setCsvPreviewErr] = useState<string | null>(null);
  const [csvPreview, setCsvPreview] = useState<CsvLastPreview | null>(null);
  /** Основной экран: таблицы аккаунтов/подписчиков или графики «Предполагаемый …». */
  const [subsMainView, setSubsMainView] = useState<"accounts" | "charts">("accounts");
  const [presumedStats, setPresumedStats] = useState<PresumedStatsResponse | null>(null);
  const [presumedStatsLoading, setPresumedStatsLoading] = useState(false);
  const [presumedStatsErr, setPresumedStatsErr] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; isErr: boolean } | null>(null);

  const showToast = (msg: string, isErr: boolean) => {
    setToast({ msg, isErr });
    window.setTimeout(() => setToast(null), 4200);
  };

  const requestAudienceStop = useCallback(() => {
    bulkStopGenerationRef.current += 1;
    bulkAbortRef.current?.abort();
    singleAbortRef.current?.abort();
    void fetch(`${subsApi()}/api/subscribers/sync/audience/stop/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      cache: "no-store",
    }).catch(() => {
      /* дашборд может быть недоступен — клиентская отмена очереди всё равно сработает */
    });
    try {
      localStorage.setItem(SUBS_BULK_ABORT_STORAGE_KEY, String(Date.now()));
    } catch {
      /* private / quota */
    }
    try {
      const bc = new BroadcastChannel(SUBS_BULK_BC_NAME);
      bc.postMessage({ type: "bulk-abort" });
      bc.close();
    } catch {
      /* */
    }
    clearSubsBulkState();
    bulkRunActiveInThisTabRef.current = false;
    bulkAbortRef.current = null;
    singleAbortRef.current = null;
    setBulkRemoteView(false);
    setBulkAudienceProgress(null);
    setBulkBusy(false);
    setRefreshingId(null);
    setSingleAudienceUsername(null);
    singleAudienceRequestRef.current = false;
    showToast("Сбор остановлен.", false);
  }, []);

  useEffect(() => {
    const onStorageAbort = (e: StorageEvent) => {
      if (e.key !== SUBS_BULK_ABORT_STORAGE_KEY || e.newValue == null) return;
      bulkStopGenerationRef.current += 1;
      bulkAbortRef.current?.abort();
      singleAbortRef.current?.abort();
    };
    window.addEventListener("storage", onStorageAbort);
    return () => window.removeEventListener("storage", onStorageAbort);
  }, []);

  useEffect(() => {
    const bc = new BroadcastChannel(SUBS_BULK_BC_NAME);
    bc.onmessage = (ev: MessageEvent<{ type?: string }>) => {
      if (ev.data?.type !== "bulk-abort") return;
      bulkStopGenerationRef.current += 1;
      bulkAbortRef.current?.abort();
      singleAbortRef.current?.abort();
    };
    return () => bc.close();
  }, []);

  useEffect(() => {
    const applyFromStorage = (raw: string | null) => {
      if (bulkRunActiveInThisTabRef.current) return;
      if (raw == null || raw === "") {
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        setBulkRunDetail(null);
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        clearSubsBulkState();
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        return;
      }
      if (!parsed || typeof parsed !== "object") {
        clearSubsBulkState();
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        setBulkRunDetail(null);
        return;
      }
      const s = parsed as Partial<SubsBulkStored>;
      if (s.v !== 1 || !s.running) {
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        setBulkRunDetail(isSubsBulkRunDetail(s.runDetail) ? s.runDetail : null);
        return;
      }
      const updatedAt = typeof s.updatedAt === "number" ? s.updatedAt : 0;
      if (Date.now() - updatedAt > SUBS_BULK_STALE_MS) {
        clearSubsBulkState();
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        setBulkRunDetail(null);
        return;
      }
      setBulkBusy(true);
      setBulkAudienceProgress(s.progress != null && isBulkProgressValue(s.progress) ? s.progress : null);
      setBulkRunDetail(isSubsBulkRunDetail(s.runDetail) ? s.runDetail : null);
      setBulkRemoteView(true);
    };

    applyFromStorage(localStorage.getItem(SUBS_BULK_LS_KEY));

    const onStorage = (e: StorageEvent) => {
      if (e.key !== SUBS_BULK_LS_KEY) return;
      applyFromStorage(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (!bulkBusy || !bulkRemoteView) return;
    const tick = () => {
      if (bulkRunActiveInThisTabRef.current) return;
      try {
        const raw = localStorage.getItem(SUBS_BULK_LS_KEY);
        if (!raw) {
          setBulkBusy(false);
          setBulkAudienceProgress(null);
          setBulkRemoteView(false);
          setBulkRunDetail(null);
          return;
        }
        const parsed = JSON.parse(raw) as Partial<SubsBulkStored>;
        if (parsed.v !== 1 || !parsed.running || typeof parsed.updatedAt !== "number") {
          setBulkBusy(false);
          setBulkAudienceProgress(null);
          setBulkRemoteView(false);
          setBulkRunDetail(isSubsBulkRunDetail(parsed.runDetail) ? parsed.runDetail : null);
          return;
        }
        if (Date.now() - parsed.updatedAt > SUBS_BULK_STALE_MS) {
          clearSubsBulkState();
          setBulkBusy(false);
          setBulkAudienceProgress(null);
          setBulkRemoteView(false);
          setBulkRunDetail(null);
          return;
        }
        if (parsed.progress != null && isBulkProgressValue(parsed.progress)) {
          setBulkAudienceProgress(parsed.progress);
        }
        if (isSubsBulkRunDetail(parsed.runDetail)) {
          setBulkRunDetail(parsed.runDetail);
        }
      } catch {
        /* */
      }
    };
    const id = window.setInterval(tick, 1500);
    return () => window.clearInterval(id);
  }, [bulkBusy, bulkRemoteView]);

  const profileFilterKey = useMemo(() => {
    if (profileFilter.kind === "all") return "all";
    if (profileFilter.kind === "none") return "none";
    return `profiles:${[...profileFilter.ids].sort((a, b) => a - b).join(",")}`;
  }, [profileFilter]);

  const buildSubscriberContextQuery = useCallback(() => {
    const qs = new URLSearchParams({ include_hidden: "1" });
    if (filterPlatform !== "all") qs.set("platform", filterPlatform);
    if (profileFilter.kind === "none") qs.set("profile_id", "none");
    else if (profileFilter.kind === "profiles" && profileFilter.ids.length > 0) {
      qs.set("profile_ids", [...profileFilter.ids].sort((a, b) => a - b).join(","));
    }
    return qs;
  }, [filterPlatform, profileFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const p = buildSubscriberContextQuery();
      const data = (await fetchJson(`${subsApi()}/api/subscribers/?${p}`)) as Overview;
      setOverview(data);
      try {
        const raw = await fetchJson(`${subsApi()}/api/subscribers/profiles/`);
        if (Array.isArray(raw)) {
          setSubsProfiles(raw as Array<{ id: number; name: string }>);
        }
      } catch {
        /* список профилей опционален */
      }
    } catch (e) {
      setOverview(null);
      setLoadErr(formatLoadNetworkErr(e));
    } finally {
      setLoading(false);
    }
  }, [buildSubscriberContextQuery]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (profileFilter.kind !== "profiles") return;
    if (!subsProfiles.length) return;
    const valid = new Set(subsProfiles.map((p) => p.id));
    const next = profileFilter.ids.filter((id) => valid.has(id));
    if (next.length === profileFilter.ids.length) return;
    if (next.length === 0) setProfileFilter({ kind: "all" });
    else setProfileFilter({ kind: "profiles", ids: next });
  }, [subsProfiles, profileFilter]);

  useEffect(() => {
    const t = window.setTimeout(() => setMemberSearch(memberSearchInput.trim()), 320);
    return () => window.clearTimeout(t);
  }, [memberSearchInput]);

  const buildMembersListQuery = useCallback(() => {
    const qs = buildSubscriberContextQuery();
    qs.set("page", String(memberPage));
    qs.set("page_size", String(SUBS_LIST_PAGE_SIZE));
    if (memberSearch) qs.set("search", memberSearch);
    if (membersFilterAccountId != null) qs.set("for_account", String(membersFilterAccountId));
    if (insightMetric === "private") qs.set("only_private", "1");
    if (insightMetric === "unique") qs.set("member_sort", "follows_desc");
    return qs;
  }, [buildSubscriberContextQuery, memberPage, memberSearch, membersFilterAccountId, insightMetric]);

  const buildMembersGlobalExportQuery = useCallback(() => {
    const qs = buildSubscriberContextQuery();
    if (memberSearch) qs.set("search", memberSearch);
    if (insightMetric === "private") qs.set("only_private", "1");
    if (insightMetric === "unique") qs.set("member_sort", "follows_desc");
    return qs;
  }, [buildSubscriberContextQuery, memberSearch, insightMetric]);

  /** Те же параметры, что у `presumed-stats` / глобального CSV — явный ключ для перезагрузки графиков при смене фильтров. */
  const presumedStatsQueryKey = useMemo(
    () => buildMembersGlobalExportQuery().toString(),
    [buildMembersGlobalExportQuery],
  );

  const toggleInsightMetric = useCallback((key: InsightMetricKey) => {
    setInsightMetric((cur) => (cur === key ? null : key));
    setMemberPage(1);
  }, []);

  useEffect(() => {
    setMemberPage(1);
  }, [memberSearch, filterPlatform, profileFilterKey, membersFilterAccountId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setMembersLoading(true);
      setMembersErr(null);
      try {
        const qs = buildMembersListQuery();
        const body = (await fetchJson(`${subsApi()}/api/subscribers/members/?${qs}`)) as MembersResp;
        if (!cancelled) setMembersData(body);
      } catch (e) {
        if (!cancelled) {
          setMembersData(null);
          setMembersErr(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setMembersLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [buildMembersListQuery]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 959px)");
    const fn = () => setNarrow(mq.matches);
    fn();
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.subsNarrow = narrow ? "1" : "0";
  }, [narrow]);

  useEffect(() => {
    if (memberCardId == null) {
      setMemberCard(null);
      setMemberCardErr(null);
      setMemberCardLoading(false);
      return;
    }
    let cancelled = false;
    setMemberCardLoading(true);
    setMemberCardErr(null);
    setMemberCard(null);
    const qs = buildSubscriberContextQuery();
    void (async () => {
      try {
        const data = (await fetchJson(
          `${subsApi()}/api/subscribers/members/${memberCardId}/?${qs}`,
        )) as MemberCardDetail;
        if (!cancelled) setMemberCard(data);
      } catch (e) {
        if (!cancelled) {
          setMemberCardErr(e instanceof Error ? e.message : String(e));
          setMemberCard(null);
        }
      } finally {
        if (!cancelled) setMemberCardLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [memberCardId, buildSubscriberContextQuery]);

  useEffect(() => {
    setMemberCardPresumedOpen(false);
  }, [memberCardId]);

  const exportMembersCsv = async () => {
    const qs = buildMembersGlobalExportQuery();
    setExportCsvBusy(true);
    try {
      const res = await fetch(`${subsApi()}/api/subscribers/members/export.csv?${qs}`, { cache: "no-store" });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const j: unknown = await res.json();
          if (typeof j === "object" && j !== null && "detail" in j) {
            detail = String((j as { detail?: unknown }).detail);
          }
        } catch {
          /* не JSON */
        }
        showToast(detail, true);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      a.href = url;
      a.download = `podpischiki_subs_${stamp}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Файл CSV сформирован", false);
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), true);
    } finally {
      setExportCsvBusy(false);
    }
  };

  const fetchLastExportPreview = async () => {
    setCsvPreviewLoading(true);
    setCsvPreviewErr(null);
    setCsvPreview(null);
    try {
      const data = (await fetchJson(
        `${subsApi()}/api/subscribers/members/export/last/preview/?limit=400`,
      )) as CsvLastPreview;
      setCsvPreview(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setCsvPreviewErr(msg);
      showToast(msg, true);
    } finally {
      setCsvPreviewLoading(false);
    }
  };

  const openLastCsvPreview = async () => {
    setCsvPreviewOpen(true);
    await fetchLastExportPreview();
  };

  const loadPresumedStats = useCallback(async () => {
    setPresumedStatsLoading(true);
    setPresumedStatsErr(null);
    try {
      const qs = buildMembersGlobalExportQuery().toString();
      const d = (await fetchJson(
        `${subsApi()}/api/subscribers/members/presumed-stats/?${qs}`,
      )) as PresumedStatsResponse;
      setPresumedStats(d);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setPresumedStatsErr(msg);
      showToast(msg, true);
    } finally {
      setPresumedStatsLoading(false);
    }
  }, [buildMembersGlobalExportQuery]);

  useEffect(() => {
    if (subsMainView !== "charts" || overview == null) return;
    void loadPresumedStats();
  }, [subsMainView, overview, presumedStatsQueryKey, loadPresumedStats]);

  const reloadMembersAndOverview = async () => {
    const qs = buildMembersListQuery();
    setMembersLoading(true);
    setMembersErr(null);
    try {
      const body = (await fetchJson(`${subsApi()}/api/subscribers/members/?${qs}`)) as MembersResp;
      setMembersData(body);
    } catch (e) {
      setMembersData(null);
      setMembersErr(e instanceof Error ? e.message : String(e));
    } finally {
      setMembersLoading(false);
    }
    await load();
  };

  const runOne = async (subsAccountId: number) => {
    if (singleAudienceRequestRef.current || bulkBusy) {
      return;
    }
    singleAbortRef.current?.abort();
    const ac = new AbortController();
    singleAbortRef.current = ac;
    const signal = ac.signal;
    const stopGenerationSnapshot = bulkStopGenerationRef.current;
    singleAudienceRequestRef.current = true;
    const uname = overview?.accounts?.find((x) => x.id === subsAccountId)?.username ?? null;
    setSingleAudienceUsername(uname);
    setRefreshingId(subsAccountId);
    try {
      await fetchJson(`${subsApi()}/api/subscribers/sync/account/${subsAccountId}/audience/`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audience_mode: "list" }),
      });
      if (signal.aborted || bulkStopGenerationRef.current !== stopGenerationSnapshot) return;
      showToast("Список подписчиков собран и импортирован", false);
      await load();
    } catch (e) {
      const aborted =
        signal.aborted ||
        bulkStopGenerationRef.current !== stopGenerationSnapshot ||
        (e instanceof DOMException && e.name === "AbortError") ||
        (e instanceof Error && e.name === "AbortError");
      if (!aborted) {
        showToast(e instanceof Error ? e.message : String(e), true);
      }
    } finally {
      singleAudienceRequestRef.current = false;
      singleAbortRef.current = null;
      setRefreshingId(null);
      setSingleAudienceUsername(null);
    }
  };

  const runBulk = async (selectedIds: number[], kind: AudiencePickKind) => {
    const rows = overview?.accounts ?? [];
    if (!rows.length) return;
    const idSet = new Set(selectedIds);
    const syncable = rows.filter((a) => idSet.has(a.id) && a.dashboard_account_id);
    if (!syncable.length) {
      showToast("Нет выбранных аккаунтов с привязкой к дашборду.", true);
      return;
    }
    try {
      await fetchJson(`${subsApi()}/api/accounts/schedule/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skip_recent_hours: bulkSkipRecentHours }),
      });
    } catch {
      /* дашборд недоступен — пропуск по часам только на клиенте */
    }
    bulkAbortRef.current?.abort();
    const ac = new AbortController();
    bulkAbortRef.current = ac;
    const signal = ac.signal;
    bulkRunActiveInThisTabRef.current = true;
    const stopGenerationSnapshot = bulkStopGenerationRef.current;
    setBulkRemoteView(false);

    setAudiencePickOpen(false);
    setBulkOperationKind(kind);
    setBulkBusy(true);
    setBulkAudienceProgress(null);
    let runDetail: SubsBulkRunDetail = {
      worker_count: 1,
      items: syncable.map((a) => ({
        account_id: a.id,
        platform: a.platform,
        username: a.username,
        status: "queued",
      })),
    };
    setBulkRunDetail(runDetail);
    setBulkRunDetailOpen(false);
    persistSubsBulkState(null, runDetail);
    const commitRunDetail = (next: SubsBulkRunDetail, prog: BulkAudienceProgress | null) => {
      runDetail = next;
      setBulkRunDetail(next);
      persistSubsBulkState(prog, next);
    };
    let ok = 0;
    let fail = 0;
    let skippedRecent = 0;
    let skippedZeroDb = 0;
    const total = syncable.length;
    let lastProg: BulkAudienceProgress | null = null;
    let finishedCount = 0;
    const runningUsernames = new Set<string>();

    const bumpParallelProgress = (phase: BulkAudienceProgress["phase"], hintUsername?: string) => {
      const running = runDetail.items.filter((it) => it.status === "running");
      const doneN = runDetail.items.filter(
        (it) => it.status === "done" || it.status === "skipped" || it.status === "error" || it.status === "cancelled",
      ).length;
      const current = Math.min(total, Math.max(doneN, finishedCount) + (running.length > 0 ? 1 : 0));
      const username =
        hintUsername ??
        (running.length === 1
          ? running[0].username
          : running.length > 1
            ? `${running.length} аккаунта`
            : "");
      const prog: BulkAudienceProgress = { total, current, username, phase };
      lastProg = prog;
      setBulkAudienceProgress(prog);
      persistSubsBulkState(prog, runDetail);
    };

    const toProcess: typeof syncable = [];
    try {
      for (const a of syncable) {
        if (signal.aborted || bulkStopGenerationRef.current !== stopGenerationSnapshot) break;
        if (kind === "collect" && bulkSkipZeroSubscribersInDb && (a.audience_count ?? 0) === 0) {
          skippedZeroDb += 1;
          commitRunDetail(
            patchSubsBulkRunDetail(runDetail, a.id, {
              status: "skipped",
              detail: "0 подписчиков в БД subs",
              worker: null,
            }),
            lastProg,
          );
          continue;
        }
        if (isSubsAudienceSyncedWithinHours(a.audience_last_synced_at, bulkSkipRecentHours)) {
          skippedRecent += 1;
          commitRunDetail(
            patchSubsBulkRunDetail(runDetail, a.id, {
              status: "skipped",
              detail:
                bulkSkipRecentHours > 0
                  ? `Съём был менее ${bulkSkipRecentHours} ч назад`
                  : "Пропущен",
              worker: null,
            }),
            lastProg,
          );
          continue;
        }
        toProcess.push(a);
      }

      const queue = interleaveAccountsByPlatform(toProcess, (a) => a.platform);
      const parallelWorkerCount = subsBulkEffectiveWorkerCount(queue, (a) => a.platform);
      runDetail = { ...runDetail, worker_count: parallelWorkerCount };
      commitRunDetail(runDetail, lastProg);
      bumpParallelProgress("account");

      const hb = window.setInterval(() => bumpSubsBulkLsTimestamp(), 30_000);
      try {
        await runSubsBulkParallelPool({
          accounts: queue,
          workerCount: parallelWorkerCount,
          platformLimits: SUBS_AUDIENCE_PLATFORM_LIMITS,
          getPlatform: (a) => a.platform,
          shouldStop: () =>
            signal.aborted || bulkStopGenerationRef.current !== stopGenerationSnapshot,
          onClaim: (a, workerSlot) => {
            runningUsernames.add(a.username);
            commitRunDetail(
              patchSubsBulkRunDetail(runDetail, a.id, {
                status: "running",
                worker: workerSlot,
                detail: undefined,
              }),
              lastProg,
            );
            bumpParallelProgress("account", a.username);
          },
          processAccount: async (a) => {
            try {
              await fetchJson(`${subsApi()}/api/subscribers/sync/account/${a.id}/audience/`, {
                method: "POST",
                signal,
                headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ audience_mode: kind === "collect" ? "list" : "enrich" }),
          });
              ok += 1;
              finishedCount += 1;
              commitRunDetail(
                patchSubsBulkRunDetail(runDetail, a.id, { status: "done", detail: undefined, worker: null }),
                lastProg,
              );
            } catch (e) {
              const aborted =
                signal.aborted ||
                bulkStopGenerationRef.current !== stopGenerationSnapshot ||
                (e instanceof DOMException && e.name === "AbortError") ||
                (e instanceof Error && e.name === "AbortError");
              if (aborted) throw e;
              fail += 1;
              finishedCount += 1;
              const msg = e instanceof Error ? e.message : String(e);
              commitRunDetail(
                patchSubsBulkRunDetail(runDetail, a.id, {
                  status: "error",
                  detail: msg.slice(0, 200),
                  worker: null,
                }),
                lastProg,
              );
            } finally {
              runningUsernames.delete(a.username);
              bumpParallelProgress("account");
            }
          },
        });
      } finally {
        window.clearInterval(hb);
      }

      const stoppedEarly = signal.aborted || bulkStopGenerationRef.current !== stopGenerationSnapshot;
      if (stoppedEarly) {
        const finalized = finalizeCancelledBulkDetail(runDetail);
        commitRunDetail(finalized, lastProg);
      }

      if (
        !signal.aborted &&
        bulkStopGenerationRef.current === stopGenerationSnapshot &&
        kind === "collect"
      ) {
        const progCsv: BulkAudienceProgress = {
          total,
          current: total,
          username: "",
          phase: "csv",
        };
        lastProg = progCsv;
        setBulkAudienceProgress(progCsv);
        persistSubsBulkState(progCsv, runDetail);
        const omitted = rows.filter((a) => a.dashboard_account_id && !idSet.has(a.id)).length;
        const parts = [`успешно ${ok}`, `ошибок ${fail}`];
        if (skippedRecent > 0) parts.push(`пропущено (недавний съём): ${skippedRecent}`);
        if (skippedZeroDb > 0) parts.push(`пропущено (0 в БД): ${skippedZeroDb}`);
        if (omitted > 0) parts.push(`не запускались (есть дашборд, не выбраны): ${omitted}`);
        let serverCsvNote = "";
        try {
          await fetchJson(`${subsApi()}/api/subscribers/members/export/last/refresh/`, {
            method: "POST",
            signal,
            headers: { "Content-Type": "application/json" },
            body: "{}",
          });
        } catch (e) {
          const csvAborted =
            signal.aborted ||
            (e instanceof DOMException && e.name === "AbortError") ||
            (e instanceof Error && e.name === "AbortError");
          if (!csvAborted) {
            serverCsvNote = ` Отчёт на сервере не обновлён: ${e instanceof Error ? e.message : String(e)}`;
          }
        }
        showToast(`Готово: ${parts.join(", ")}${serverCsvNote}`, fail > 0 || Boolean(serverCsvNote));
      }
      await load();
    } catch (e) {
      if (!signal.aborted) {
        showToast(e instanceof Error ? e.message : String(e), true);
      }
    } finally {
      clearSubsBulkState();
      bulkRunActiveInThisTabRef.current = false;
      bulkAbortRef.current = null;
      setBulkAudienceProgress(null);
      setBulkBusy(false);
      setBulkRemoteView(false);
    }
  };

  const syncFromDashboard = async () => {
    setSyncBusy(true);
    try {
      const out = (await fetchJson(`${subsApi()}/api/subscribers/sync/dashboard/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })) as {
        ok?: boolean;
        profiles_upserted?: number;
        accounts_upserted?: number;
      } | null;
      const pn = out?.profiles_upserted;
      const an = out?.accounts_upserted;
      if (typeof pn === "number" && typeof an === "number") {
        showToast(`С дашборда: профилей ${pn}, аккаунтов ${an}`, false);
      } else {
        showToast("Профили и аккаунты подтянуты с дашборда", false);
      }
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), true);
    } finally {
      setSyncBusy(false);
    }
  };

  const s = overview?.summary;
  const accounts = overview?.accounts ?? [];
  const syncableAccounts = useMemo(
    () => accounts.filter((a) => a.dashboard_account_id),
    [accounts],
  );

  const bulkAudienceBarPct = useMemo(() => {
    const p = bulkAudienceProgress;
    if (!p || p.total <= 0) return 0;
    if (p.phase === "csv") return 100;
    if (p.phase === "pause") {
      return Math.min(99, Math.round((p.current / p.total) * 100));
    }
    return Math.min(98, Math.round(((p.current - 0.35) / p.total) * 100));
  }, [bulkAudienceProgress]);

  const bulkModalAccounts = useMemo(() => {
    let rows = accounts;
    if (bulkModalPlatforms.length > 0) {
      const pset = new Set(bulkModalPlatforms);
      rows = rows.filter((a) => pset.has(a.platform));
    }
    if (bulkModalProfileKeys.length > 0) {
      const wantNone = bulkModalProfileKeys.includes("none");
      const wantIds = new Set(
        bulkModalProfileKeys
          .filter((k) => k.startsWith("id:"))
          .map((k) => Number.parseInt(k.slice(3), 10))
          .filter((n) => Number.isFinite(n)),
      );
      rows = rows.filter((a) => {
        if (a.profile_id == null) return wantNone;
        return wantIds.has(a.profile_id);
      });
    }
    return rows;
  }, [accounts, bulkModalPlatforms, bulkModalProfileKeys]);

  const bulkModalSyncableAccounts = useMemo(
    () => bulkModalAccounts.filter((a) => a.dashboard_account_id),
    [bulkModalAccounts],
  );

  const enrichPickAccounts = useMemo(() => {
    let rows = bulkModalAccounts.filter((a) => (a.audience_count ?? 0) > 0);
    const q = enrichAccountSearch.trim().toLowerCase();
    if (q) {
      rows = rows.filter((a) => {
        const u = a.username.toLowerCase();
        const d = (a.display_name || "").toLowerCase();
        const p = (a.profile_name || "").toLowerCase();
        return u.includes(q) || d.includes(q) || p.includes(q);
      });
    }
    return rows;
  }, [bulkModalAccounts, enrichAccountSearch]);

  const enrichPickSyncableAccounts = useMemo(
    () => enrichPickAccounts.filter((a) => a.dashboard_account_id),
    [enrichPickAccounts],
  );

  const audiencePickListAccounts = audiencePickKind === "enrich" ? enrichPickAccounts : bulkModalAccounts;
  const audiencePickSyncableAccounts =
    audiencePickKind === "enrich" ? enrichPickSyncableAccounts : bulkModalSyncableAccounts;

  const bulkModalAccountsOrdered = useMemo(() => {
    const rows = [...audiencePickListAccounts];
    if (bulkModalAudienceSort === "default") return rows;
    rows.sort((a, b) => {
      const ka = audienceSyncTsMs(a.audience_last_synced_at);
      const kb = audienceSyncTsMs(b.audience_last_synced_at);
      if (bulkModalAudienceSort === "sync_desc") {
        const va = ka ?? Number.NEGATIVE_INFINITY;
        const vb = kb ?? Number.NEGATIVE_INFINITY;
        if (vb !== va) return vb - va;
      } else {
        const va = ka ?? Number.POSITIVE_INFINITY;
        const vb = kb ?? Number.POSITIVE_INFINITY;
        if (va !== vb) return va - vb;
      }
      return a.username.localeCompare(b.username, "ru");
    });
    return rows;
  }, [audiencePickListAccounts, bulkModalAudienceSort]);

  const bulkPickCount = useMemo(
    () => audiencePickSyncableAccounts.filter((a) => bulkSelectedIds.has(a.id)).length,
    [audiencePickSyncableAccounts, bulkSelectedIds],
  );

  /** Сколько из выбранных реально пойдут в POST (без пропуска «недавно сняты» и опционально без 0 в БД). */
  const bulkPickWillRunCount = useMemo(() => {
    return audiencePickSyncableAccounts.filter((a) => {
      if (!bulkSelectedIds.has(a.id)) return false;
      if (audiencePickKind === "collect" && bulkSkipZeroSubscribersInDb && (a.audience_count ?? 0) === 0) {
        return false;
      }
      if (audiencePickKind === "enrich" && (a.audience_count ?? 0) === 0) return false;
      return !isSubsAudienceSyncedWithinHours(a.audience_last_synced_at, bulkSkipRecentHours);
    }).length;
  }, [
    audiencePickKind,
    audiencePickSyncableAccounts,
    bulkSelectedIds,
    bulkSkipRecentHours,
    bulkSkipZeroSubscribersInDb,
  ]);

  const syncableAccountsWithSubs = useMemo(
    () => syncableAccounts.filter((a) => (a.audience_count ?? 0) > 0),
    [syncableAccounts],
  );

  useEffect(() => {
    if (!audiencePickOpen) return;
    setBulkSelectedIds((prev) => new Set([...prev].filter((id) => audiencePickListAccounts.some((a) => a.id === id))));
  }, [audiencePickOpen, audiencePickListAccounts]);

  useEffect(() => {
    if (!audiencePickOpen) return;
    let cancelled = false;
    void (async () => {
      try {
        const sched = (await fetchJson(`${subsApi()}/api/accounts/schedule/`)) as {
          skip_recent_hours?: number;
        } | null;
        if (cancelled || sched == null) return;
        if (typeof sched.skip_recent_hours === "number" && Number.isFinite(sched.skip_recent_hours)) {
          setBulkSkipRecentHours(sched.skip_recent_hours);
        }
      } catch {
        /* дашборд недоступен */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [audiencePickOpen]);

  useEffect(() => {
    if (!audiencePickOpen || bulkBusy) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAudiencePickOpen(false);
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [audiencePickOpen, bulkBusy]);

  useEffect(() => {
    if (!csvPreviewOpen) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCsvPreviewOpen(false);
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [csvPreviewOpen]);

  const filteredAccounts = useMemo(() => {
    const q = accountSearch.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((a) => {
      const u = a.username.toLowerCase();
      const d = (a.display_name || "").toLowerCase();
      const p = a.platform.toLowerCase();
      const pn = (a.profile_name || "").toLowerCase();
      return u.includes(q) || d.includes(q) || p.includes(q) || pn.includes(q);
    });
  }, [accounts, accountSearch]);

  const displayAccountsForTable = useMemo(() => {
    if (insightMetric == null) return filteredAccounts;
    let rows = filteredAccounts;
    if (insightMetric === "with_data") {
      rows = rows.filter((a) => a.audience_count > 0);
    }
    rows = [...rows];
    if (insightMetric === "accounts") {
      rows.sort((a, b) => a.username.localeCompare(b.username, "ru"));
    } else if (insightMetric === "unique" || insightMetric === "with_data") {
      rows.sort((a, b) => (b.audience_count || 0) - (a.audience_count || 0));
    }
    return rows;
  }, [filteredAccounts, insightMetric]);

  const accountTablePages = useMemo(
    () => Math.max(1, Math.ceil(displayAccountsForTable.length / SUBS_LIST_PAGE_SIZE)),
    [displayAccountsForTable],
  );

  const pagedAccountsForTable = useMemo(() => {
    const start = (accountTablePage - 1) * SUBS_LIST_PAGE_SIZE;
    return displayAccountsForTable.slice(start, start + SUBS_LIST_PAGE_SIZE);
  }, [displayAccountsForTable, accountTablePage]);

  useEffect(() => {
    setAccountTablePage(1);
  }, [accountSearch, insightMetric, profileFilterKey, filterPlatform]);

  useEffect(() => {
    setAccountTablePage((p) => {
      const next = Math.min(Math.max(1, p), accountTablePages);
      return next === p ? p : next;
    });
  }, [accountTablePages]);

  const membersFilterAccountLabel = useMemo(() => {
    if (membersFilterAccountId == null) return null;
    const a = accounts.find((x) => x.id === membersFilterAccountId);
    return a ? `@${a.username} · ${a.platform}` : null;
  }, [accounts, membersFilterAccountId]);

  useEffect(() => {
    if (membersFilterAccountId == null || !overview) return;
    if (!overview.accounts.some((x) => x.id === membersFilterAccountId)) {
      setMembersFilterAccountId(null);
    }
  }, [overview, membersFilterAccountId]);

  const memberTotal = membersData?.count ?? 0;
  const memberPages = Math.max(1, Math.ceil(memberTotal / SUBS_LIST_PAGE_SIZE));
  const memberRows = membersData?.results ?? [];

  return (
    <div className="subs-shell">
      <header className="subs-header">
        <div className="subs-header-row">
          <div className="subs-header-left">
            <div className="subs-header-brand-metrics">
              <div className="subs-header-brand">
                <div className="mono subs-brand-kicker">SUBS</div>
                <div className="subs-brand-title">Подписчики</div>
              </div>
              {overview && s ? (
                <div className="subs-metrics subs-metrics--header">
                  {(
                    [
                      ["Аккаунтов", fmtNum(s.tracked_accounts_count), "accounts" as const, "Сортировка по нику"],
                      [
                        "Уникальных подписчиков",
                        fmtNum(s.unique_subscribers_total),
                        "unique" as const,
                        "Подписчики: по числу наших аккаунтов",
                      ],
                      ["Приватных подписчиков", fmtNum(s.private_subscribers_total), "private" as const, "Только закрытые профили"],
                      [
                        "Подписчиков с данными",
                        fmtNum(s.accounts_with_audience_rows),
                        "with_data" as const,
                        "Аккаунты с подписчиками в базе",
                      ],
                    ] as const
                  ).map(([label, value, key, hint]) => {
                    const active = insightMetric === key;
                    const accent = key === "unique";
                    return (
                      <button
                        key={key}
                        type="button"
                        title={hint}
                        aria-pressed={active}
                        aria-label={`${label}: ${value}. Нажмите, чтобы применить или снять фильтр.`}
                        onClick={() => toggleInsightMetric(key)}
                        className={`subs-metric subs-metric--btn subs-metric--stat${accent ? " subs-metric--accent" : ""}${active ? " subs-metric--active" : ""}`}
                      >
                        <div className="mono subs-metric-label subs-metric-label--stat">{label}</div>
                        <div className="subs-metric-value tnum">{value}</div>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </div>
          <div className="subs-header-right">
            {overview ? (
              <div className="subs-header-collect">
                <button
                  type="button"
                  disabled={bulkBusy || loading || !syncableAccounts.length}
                  title={
                    syncableAccounts.length
                      ? `Открыть выбор аккаунтов (${syncableAccounts.length} с привязкой к дашборду)`
                      : "Нет аккаунтов с привязкой к дашборду"
                  }
                  onClick={() => {
                    if (!syncableAccounts.length) {
                      showToast("Нет аккаунтов с привязкой к дашборду — сначала «Синхр. с дашборда»", true);
                      return;
                    }
                    setAudiencePickKind("collect");
                    setBulkModalPlatforms([]);
                    setBulkModalProfileKeys([]);
                    setEnrichAccountSearch("");
                    setBulkSelectedIds(new Set(syncableAccounts.map((a) => a.id)));
                    setAudiencePickOpen(true);
                  }}
                  className="subs-btn-emphasis"
                >
                  {bulkBusy && bulkOperationKind === "collect" ? "Сбор…" : "Собрать подписчиков"}
                </button>
                <button
                  type="button"
                  disabled={bulkBusy || loading || !syncableAccountsWithSubs.length}
                  title={
                    syncableAccountsWithSubs.length
                      ? `Обновить профили (${syncableAccountsWithSubs.length} аккаунтов с подписчиками в БД)`
                      : "Сначала соберите список подписчиков"
                  }
                  onClick={() => {
                    if (!syncableAccountsWithSubs.length) {
                      showToast("Нет аккаунтов с подписчиками в БД — сначала «Собрать подписчиков»", true);
                      return;
                    }
                    setAudiencePickKind("enrich");
                    setBulkModalPlatforms([]);
                    setBulkModalProfileKeys([]);
                    setEnrichAccountSearch("");
                    setBulkSelectedIds(new Set(syncableAccountsWithSubs.map((a) => a.id)));
                    setAudiencePickOpen(true);
                  }}
                  className="subs-btn subs-btn--muted"
                  style={{
                    padding: "10px 16px",
                    fontSize: 13,
                    fontWeight: 600,
                    border: "1px solid var(--line-strong)",
                    background: "rgba(255,255,255,0.04)",
                  }}
                >
                  {bulkBusy && bulkOperationKind === "enrich" ? "Обновление…" : "Обновить профили"}
                </button>
              </div>
            ) : null}
            <div className="subs-view-tabs subs-view-tabs--header" role="tablist" aria-label="Вид экрана">
            <button
              type="button"
              role="tab"
              aria-selected={subsMainView === "accounts"}
              className={`subs-view-tab${subsMainView === "accounts" ? " subs-view-tab--active" : ""}`}
              onClick={() => setSubsMainView("accounts")}
            >
              Аккаунты
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subsMainView === "charts"}
              className={`subs-view-tab${subsMainView === "charts" ? " subs-view-tab--active" : ""}`}
              onClick={() => setSubsMainView("charts")}
            >
              Графики
            </button>
          </div>
          </div>
        </div>
      </header>

      <main className="subs-main" data-layout="subscribers">
        {toast && (
          <div className={`subs-banner ${toast.isErr ? "subs-banner--err" : "subs-banner--ok"}`}>{toast.msg}</div>
        )}

        {bulkBusy ? (
          <div className="subs-collect-dock" role="status" aria-live="polite">
            {bulkAudienceProgress ? (
              <div className="subs-collect-dock-inner">
                <div className="subs-collect-dock-row" style={{ alignItems: "center" }}>
                  <span className="subs-collect-dock-title">
                    {bulkOperationKind === "enrich" ? "Обновление профилей" : "Сбор подписчиков"}
                  </span>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      marginLeft: "auto",
                      flexShrink: 0,
                      flexWrap: "wrap",
                      justifyContent: "flex-end",
                    }}
                  >
                    <span className="subs-collect-dock-counter mono tnum">
                      {bulkAudienceProgress.phase === "csv"
                        ? `${bulkAudienceProgress.total} / ${bulkAudienceProgress.total}`
                        : `${bulkAudienceProgress.current} / ${bulkAudienceProgress.total}`}
                    </span>
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--muted"
                      onClick={() => setBulkRunDetailOpen(true)}
                    >
                      Подробнее
                    </button>
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--danger-text"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        requestAudienceStop();
                      }}
                    >
                      Остановить
                    </button>
                  </div>
                </div>
                <div className="subs-collect-dock-sub mono">
                  {bulkRemoteView ? (
                    <span style={{ display: "block", marginBottom: 6, color: "var(--accent)", fontWeight: 500 }}>
                      Сбор идёт в другой вкладке — здесь только отображение; «Остановить» срабатывает для всех вкладок.
                    </span>
                  ) : null}
                  {bulkAudienceProgress.phase === "csv"
                    ? "Сохранение отчёта CSV на сервере…"
                    : bulkAudienceProgress.phase === "pause"
                      ? `Пауза перед аккаунтом ${bulkAudienceProgress.current} из ${bulkAudienceProgress.total} · @${bulkAudienceProgress.username}`
                      : `Аккаунт ${bulkAudienceProgress.current} из ${bulkAudienceProgress.total} · @${bulkAudienceProgress.username}`}
                </div>
                <div className="subs-collect-bar" aria-hidden>
                  <div className="subs-collect-bar-fill" style={{ width: `${bulkAudienceBarPct}%` }} />
                </div>
              </div>
            ) : (
              <div className="subs-collect-dock-inner">
                <div className="subs-collect-dock-row" style={{ alignItems: "center" }}>
                  <span className="subs-collect-dock-title">
                    {bulkOperationKind === "enrich" ? "Обновление профилей" : "Сбор подписчиков"}
                  </span>
                  <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexShrink: 0 }}>
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--muted"
                      onClick={() => setBulkRunDetailOpen(true)}
                    >
                      Подробнее
                    </button>
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--danger-text"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        requestAudienceStop();
                      }}
                    >
                      Остановить
                    </button>
                  </div>
                </div>
                <div className="subs-collect-dock-sub">
                  {bulkRemoteView ? (
                    <span style={{ display: "block", marginBottom: 6, color: "var(--accent)", fontWeight: 500 }}>
                      Сбор идёт в другой вкладке — здесь только отображение; «Остановить» срабатывает для всех вкладок.
                    </span>
                  ) : null}
                  <span className="mono">Подготовка…</span>
                </div>
                <div className="subs-collect-bar subs-collect-bar--indeterminate" aria-hidden>
                  <div className="subs-collect-bar-indeterminate" />
                </div>
              </div>
            )}
          </div>
        ) : refreshingId != null ? (
          <div className="subs-collect-dock" role="status" aria-live="polite">
            <div className="subs-collect-dock-inner">
              <div className="subs-collect-dock-row" style={{ alignItems: "center" }}>
                <span className="subs-collect-dock-title">Сбор подписчиков</span>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    marginLeft: "auto",
                    flexShrink: 0,
                  }}
                >
                  <span className="subs-collect-dock-counter mono tnum">1 / 1</span>
                  <button
                    type="button"
                    className="subs-btn subs-btn--sm subs-btn--danger-text"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      requestAudienceStop();
                    }}
                  >
                    Остановить
                  </button>
                </div>
              </div>
              <div className="subs-collect-dock-sub mono">
                @{singleAudienceUsername ?? "…"} — запрос к дашборду, подождите…
              </div>
              <div className="subs-collect-bar subs-collect-bar--indeterminate" aria-hidden>
                <div className="subs-collect-bar-indeterminate" />
              </div>
            </div>
          </div>
        ) : null}

        {memberCardId != null && (
          <div
            className="subs-modal-overlay"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 78,
              background: "rgba(0,0,0,0.82)",
              backdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            role="dialog"
            aria-modal
            aria-labelledby="subs-member-card-title"
            onClick={(e) => {
              if (e.target === e.currentTarget) setMemberCardId(null);
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              className="subs-modal-panel"
              style={{
                maxWidth: 480,
                width: "100%",
                maxHeight: "min(88vh, 640px)",
                overflow: "auto",
                borderRadius: 16,
                border: "1px solid var(--line-strong)",
                background: "var(--panel)",
                padding: 20,
                boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
              }}
            >
              <div className="subs-modal-title-row">
                <h3 id="subs-member-card-title" style={{ margin: 0, fontSize: 16, color: "var(--ink)" }}>
                  {memberCardLoading
                    ? "Загрузка…"
                    : memberCard
                      ? `@${memberCard.username}`
                      : "Подписчик"}
                </h3>
                <button
                  type="button"
                  className="subs-btn subs-btn--muted subs-btn--sm"
                  onClick={() => setMemberCardId(null)}
                  aria-label="Закрыть"
                >
                  ×
                </button>
              </div>
              {memberCardErr ? (
                <p style={{ margin: "12px 0 0", fontSize: 13, color: "var(--danger)" }}>{memberCardErr}</p>
              ) : null}
              {memberCard && !memberCardLoading ? (
                <div style={{ marginTop: 14, fontSize: 13, color: "var(--ink-dim)", lineHeight: 1.5 }}>
                  <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
                    {memberCard.avatar_url ? (
                      <img
                        src={memberCard.avatar_url}
                        alt=""
                        width={56}
                        height={56}
                        style={{ borderRadius: 12, objectFit: "cover", flexShrink: 0 }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 56,
                          height: 56,
                          borderRadius: 12,
                          background: "var(--surface-2)",
                          flexShrink: 0,
                        }}
                      />
                    )}
                    <div>
                      <div style={{ color: "var(--ink-mute)", fontSize: 11, textTransform: "uppercase" }}>
                        {memberCard.platform}
                        {memberCard.is_private ? " · закрытый" : ""}
                      </div>
                      {memberCard.display_name ? (
                        <div style={{ color: "var(--ink)", fontWeight: 600 }}>{memberCard.display_name}</div>
                      ) : null}
                      <div className="tnum" style={{ marginTop: 6, fontSize: 12 }}>
                        Подписчики: {fmtNum(memberCard.follower_count)} · Подписки: {fmtNum(memberCard.following_count)}
                        {memberCard.platform === "tiktok" || memberCard.platform === "instagram"
                          ? ` · Лайки: ${fmtNum(memberCard.like_count)}`
                          : null}
                      </div>
                      {memberCard.external_id ? (
                        <div className="mono" style={{ fontSize: 11, marginTop: 4, wordBreak: "break-all" }}>
                          id: {memberCard.external_id}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {memberCard.bio ? (
                    <p style={{ margin: "0 0 12px", color: "var(--ink)", whiteSpace: "pre-wrap", fontSize: 13 }}>
                      {memberCard.bio}
                    </p>
                  ) : (
                    <p style={{ margin: "0 0 12px", fontSize: 12 }}>Био не сохранено.</p>
                  )}
                  <p style={{ margin: "0 0 6px", fontSize: 11, color: "var(--ink-mute)", textTransform: "uppercase" }}>
                    Подписан на отслеживаемые аккаунты ({memberCard.follows_tracked_accounts})
                  </p>
                  <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink)" }}>
                    {memberCard.tracked_accounts.map((a) => (
                      <li key={`${a.subs_account_id}-${a.platform}`} style={{ marginBottom: 6 }}>
                        <span style={{ color: "var(--ink-dim)" }}>{a.platform}</span>{" "}
                        <strong>@{a.username}</strong>
                        {a.profile_name ? (
                          <span style={{ color: "var(--ink-mute)", fontWeight: 400 }}> · {a.profile_name}</span>
                        ) : null}
                        {a.last_synced_at ? (
                          <span style={{ display: "block", fontSize: 11, color: "var(--ink-mute)" }}>
                            Синхр. {fmtDate(a.last_synced_at)}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  {memberCardPresumedOpen ? (
                    <div
                      style={{
                        marginTop: 14,
                        padding: "12px 14px",
                        borderRadius: 12,
                        border: "1px solid var(--line)",
                        background: "rgba(0,0,0,0.22)",
                      }}
                    >
                      <div className="mono subs-hint" style={{ marginBottom: 10, letterSpacing: "0.06em" }}>
                        Предполагаемые данные
                      </div>
                      <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--ink-mute)", lineHeight: 1.45 }}>
                        Оценка по нику, отображаемому имени и био (как в CSV). Не фактические сведения о человеке.
                      </p>
                      {memberCard.presumed && memberCard.presumed.length > 0 ? (
                        <dl style={{ margin: 0, display: "grid", gap: "8px 12px", gridTemplateColumns: "minmax(0,1fr)" }}>
                          {memberCard.presumed.map((row) => (
                            <div
                              key={row.label}
                              style={{
                                display: "grid",
                                gridTemplateColumns: "minmax(0,1fr)",
                                gap: 4,
                                paddingBottom: 8,
                                borderBottom: "1px solid rgba(255,255,255,0.06)",
                              }}
                            >
                              <dt style={{ margin: 0, fontSize: 12, color: "var(--ink-mute)", fontWeight: 500 }}>
                                {row.label}
                              </dt>
                              <dd style={{ margin: 0, fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>{row.value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : (
                        <p style={{ margin: 0, fontSize: 13, color: "var(--ink-mute)" }}>
                          Нет данных: обновите сервер subs до версии с полем <span className="mono">presumed</span> в ответе
                          карточки.
                        </p>
                      )}
                    </div>
                  ) : null}
                  <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 10 }}>
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--muted"
                      onClick={() => setMemberCardPresumedOpen((v) => !v)}
                      title="Те же колонки, что «Предполагаемый …» в экспорте CSV"
                      style={
                        memberCardPresumedOpen
                          ? { borderColor: "var(--accent)", color: "var(--accent)", boxShadow: "0 0 0 1px var(--accent)" }
                          : undefined
                      }
                    >
                      {memberCardPresumedOpen ? "Скрыть оценки" : "Предполагаемые данные"}
                    </button>
                    {profileUrl(memberCard.platform, memberCard.username) ? (
                      <a
                        href={profileUrl(memberCard.platform, memberCard.username) || "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="subs-btn subs-btn--sm subs-btn--muted"
                      >
                        Открыть на {subsPlatformLabel(memberCard.platform)}
                      </a>
                    ) : null}
                    <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={() => setMemberCardId(null)}>
                      Закрыть
                    </button>
                  </div>
                  {memberCard.updated_at ? (
                    <p style={{ margin: "14px 0 0", fontSize: 11, color: "var(--ink-mute)" }}>
                      Данные в subs обновлены: {fmtDate(memberCard.updated_at)}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        )}

        {audiencePickOpen && !bulkBusy && (
          <div
            className="subs-modal-overlay"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 85,
              background: "rgba(0,0,0,0.82)",
              backdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget) setAudiencePickOpen(false);
            }}
          >
            <div
              role="dialog"
              aria-modal
              aria-labelledby="subs-audience-pick-modal-title"
              className="subs-modal-panel"
              onClick={(e) => e.stopPropagation()}
              style={{
                maxWidth: 560,
                width: "100%",
                maxHeight: "min(92vh, 720px)",
                display: "flex",
                flexDirection: "column",
                borderRadius: 16,
                border: "1px solid var(--line-strong)",
                background: "var(--panel)",
                padding: 20,
                boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
              }}
            >
              <h3 id="subs-audience-pick-modal-title" style={{ margin: "0 0 8px", fontSize: 17, color: "var(--ink)" }}>
                {audiencePickKind === "enrich" ? "Обновление профилей подписчиков" : "Сбор подписчиков"}
              </h3>
              <p style={{ margin: "0 0 14px", fontSize: 12, color: "var(--ink-mute)", lineHeight: 1.45 }}>
                {audiencePickKind === "enrich"
                  ? "Для каждого выбранного отслеживаемого аккаунта обновятся bio, счётчики и аватары уже сохранённых подписчиков (без повторного съёма списка)."
                  : "Снимается список подписчиков с площадки (модалка followers). Профили подписчиков не обновляются — используйте «Обновить профили»."}
              </p>
              {audiencePickKind === "enrich" ? (
                <div className="subs-field-wrap" style={{ marginBottom: 12 }}>
                  <input
                    value={enrichAccountSearch}
                    onChange={(e) => setEnrichAccountSearch(e.target.value)}
                    placeholder="Поиск по @нику, имени или профилю…"
                    className="subs-field"
                  />
                  <span className="subs-field-icon">⌕</span>
                </div>
              ) : null}
              <div style={{ marginBottom: 14 }}>
                <button
                  type="button"
                  onClick={() => void syncFromDashboard()}
                  disabled={syncBusy || loading}
                  className="subs-btn subs-btn--sync"
                  style={{ width: "100%", justifyContent: "center" }}
                >
                  {syncBusy ? "…" : "Синхр. с дашборда"}
                </button>
              </div>
              <div style={{ marginBottom: 12 }}>
                <div className="mono subs-hint" style={{ marginBottom: 6 }}>
                  Площадка
                </div>
                <div className="subs-modal-chip-row">
                  <button
                    type="button"
                    onClick={() => setBulkModalPlatforms([])}
                    className={`subs-chip${bulkModalPlatforms.length === 0 ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                  >
                    Все
                  </button>
                  {PLATFORMS.map((meta) => {
                    const active =
                      bulkModalPlatforms.length > 0 ? bulkModalPlatforms.includes(meta.id) : false;
                    return (
                      <button
                        key={meta.id}
                        type="button"
                        onClick={() => {
                          setBulkModalPlatforms((prev) => {
                            const has = prev.includes(meta.id);
                            if (has) return prev.filter((x) => x !== meta.id);
                            return [...prev, meta.id];
                          });
                        }}
                        className={`subs-chip${active ? " subs-chip--active" : ""}`}
                        style={{ fontSize: 12 }}
                      >
                        <span className="subs-dot" style={{ background: meta.color }} />
                        {meta.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div style={{ marginBottom: 12 }}>
                <div className="mono subs-hint" style={{ marginBottom: 6 }}>
                  Профиль
                </div>
                <div className="subs-modal-chip-row">
                  <button
                    type="button"
                    onClick={() => setBulkModalProfileKeys([])}
                    className={`subs-chip${bulkModalProfileKeys.length === 0 ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                  >
                    Все профили
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setBulkModalProfileKeys((prev) => {
                        const has = prev.includes("none");
                        if (has) return prev.filter((x) => x !== "none");
                        return [...prev, "none"];
                      });
                    }}
                    className={`subs-chip${bulkModalProfileKeys.includes("none") ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                  >
                    Без профиля
                  </button>
                  {subsProfiles.map((p) => {
                    const key = `id:${p.id}`;
                    const active = bulkModalProfileKeys.includes(key);
                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => {
                          setBulkModalProfileKeys((prev) => {
                            const has = prev.includes(key);
                            if (has) return prev.filter((x) => x !== key);
                            return [...prev, key];
                          });
                        }}
                        className={`subs-chip${active ? " subs-chip--active" : ""}`}
                        style={{ fontSize: 12 }}
                      >
                        {p.name}
                      </button>
                    );
                  })}
                </div>
              </div>
              {audiencePickKind === "collect" ? (
                <label
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    marginBottom: 12,
                    cursor: "pointer",
                    fontSize: 13,
                    color: "var(--ink-dim)",
                    lineHeight: 1.45,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={bulkSkipZeroSubscribersInDb}
                    onChange={(e) => setBulkSkipZeroSubscribersInDb(e.target.checked)}
                    style={{ marginTop: 3, flexShrink: 0 }}
                  />
                  <span>Пропускать с 0 подписчиков в БД</span>
                </label>
              ) : null}
              <div style={{ marginBottom: 12 }}>
                <div
                  className="mono subs-hint"
                  style={{
                    marginBottom: 8,
                    fontSize: 11,
                    letterSpacing: "0.2em",
                    color: "var(--ink-mute)",
                  }}
                >
                  ПРОПУСКАТЬ НЕДАВНО ОБНОВЛЁННЫЕ
                </div>
                <div className="subs-modal-chip-row">
                  {SUBS_BULK_SKIP_RECENT_HOURS.map((h) => (
                    <button
                      key={h}
                      type="button"
                      className={`subs-chip${bulkSkipRecentHours === h ? " subs-chip--active" : ""}`}
                      style={{ fontSize: 12 }}
                      onClick={() => setBulkSkipRecentHours(h)}
                    >
                      {h === 0 ? "Не пропускать" : `< ${h}ч`}
                    </button>
                  ))}
                </div>
              </div>
              {bulkSkipRecentHours > 0 ? (
                <p
                  style={{
                    fontSize: 12,
                    color: "rgba(250,204,21,0.92)",
                    margin: "0 0 12px",
                    lineHeight: 1.45,
                  }}
                >
                  Аккаунты с съёмом аудитории за последние {bulkSkipRecentHours} ч будут пропущены (как в автообновлении
                  дашборда).
                </p>
              ) : null}
              <div style={{ marginBottom: 12 }}>
                <div className="mono subs-hint" style={{ marginBottom: 6 }}>
                  Сортировка
                </div>
                <div className="subs-modal-chip-row">
                  <button
                    type="button"
                    className={`subs-chip${bulkModalAudienceSort === "default" ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                    onClick={() => setBulkModalAudienceSort("default")}
                  >
                    Как в списке
                  </button>
                  <button
                    type="button"
                    className={`subs-chip${bulkModalAudienceSort === "sync_desc" ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                    onClick={() => setBulkModalAudienceSort("sync_desc")}
                  >
                    Новее сверху
                  </button>
                  <button
                    type="button"
                    className={`subs-chip${bulkModalAudienceSort === "sync_asc" ? " subs-chip--active" : ""}`}
                    style={{ fontSize: 12 }}
                    onClick={() => setBulkModalAudienceSort("sync_asc")}
                  >
                    Старее сверху
                  </button>
                </div>
              </div>
              <div className="subs-modal-inline-actions">
                <button
                  type="button"
                  className="subs-btn subs-btn--sm subs-btn--muted"
                  onClick={() => setBulkSelectedIds(new Set(audiencePickSyncableAccounts.map((a) => a.id)))}
                >
                  Выбрать все с дашбордом
                </button>
                <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={() => setBulkSelectedIds(new Set())}>
                  Снять выбор
                </button>
              </div>
              <div
                className="subs-bulk-pick-scroll"
                style={{
                  flex: 1,
                  minHeight: 0,
                  overflow: "auto",
                  border: "1px solid var(--line)",
                  borderRadius: 12,
                  padding: "8px 10px",
                  marginBottom: 16,
                }}
              >
                {audiencePickListAccounts.length === 0 ? (
                  <p className="subs-muted" style={{ margin: 8 }}>
                    Нет аккаунтов по текущим фильтрам.
                  </p>
                ) : (
                  bulkModalAccountsOrdered.map((a) => {
                    const can = !!a.dashboard_account_id;
                    const checked = bulkSelectedIds.has(a.id);
                    const meta = PLATFORMS.find((p) => p.id === a.platform);
                    const skipByRecent =
                      can &&
                      bulkSkipRecentHours > 0 &&
                      isSubsAudienceSyncedWithinHours(a.audience_last_synced_at, bulkSkipRecentHours);
                    const skipByZeroDb =
                      audiencePickKind === "collect" &&
                      bulkSkipZeroSubscribersInDb &&
                      can &&
                      (a.audience_count ?? 0) === 0;
                    const skipHighlight = checked && (skipByRecent || skipByZeroDb);
                    const showMembersPreview =
                      audiencePickKind === "enrich" && can && (a.audience_count ?? 0) > 0;
                    return (
                      <label
                        key={a.id}
                        className={`subs-bulk-pick-row${showMembersPreview ? " subs-bulk-pick-row--with-actions" : ""}`}
                        style={{
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 10,
                          padding: "10px 8px",
                          borderRadius: 10,
                          cursor: can ? "pointer" : "default",
                          opacity: can ? 1 : 0.55,
                          border: skipHighlight ? "1px solid rgba(255,255,255,0.14)" : "1px solid transparent",
                          background: skipHighlight ? "rgba(255,255,255,0.03)" : undefined,
                        }}
                      >
                        <input
                          type="checkbox"
                          style={{ marginTop: 3 }}
                          disabled={!can}
                          checked={can && checked}
                          onChange={() => {
                            if (!can) return;
                            setBulkSelectedIds((prev) => {
                              const n = new Set(prev);
                              if (n.has(a.id)) n.delete(a.id);
                              else n.add(a.id);
                              return n;
                            });
                          }}
                        />
                        <span style={{ flexShrink: 0, marginTop: 1 }}>
                          {meta ? (
                            <span className="subs-dot" style={{ background: meta.color, verticalAlign: "middle" }} />
                          ) : null}{" "}
                          <span style={{ fontSize: 11, color: "var(--ink-dim)" }}>{a.platform}</span>
                        </span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600, color: "var(--ink)" }}>@{a.username}</span>
                          {a.display_name ? (
                            <span style={{ display: "block", fontSize: 12, color: "var(--ink-mute)", marginTop: 2 }}>
                              {a.display_name}
                            </span>
                          ) : null}
                          <span
                            className="tnum"
                            style={{ display: "block", fontSize: 11, color: "var(--ink-dim)", marginTop: 4 }}
                          >
                            {audiencePickKind === "enrich"
                              ? `Подписчиков в БД: ${fmtNum(a.audience_count ?? 0)}`
                              : `Снято: ${fmtDate(a.audience_last_synced_at)}`}
                          </span>
                          {!can ? (
                            <span style={{ display: "block", fontSize: 11, color: "var(--ink-dim)", marginTop: 4 }}>
                              Нет связи с дашбордом
                            </span>
                          ) : null}
                        </span>
                        {showMembersPreview ? (
                          <button
                            type="button"
                            className="subs-icon-btn"
                            title="Список подписчиков в БД"
                            aria-label={`Подписчики @${a.username}`}
                            disabled={bulkBusy}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setMembersPreviewAccount({
                                id: a.id,
                                username: a.username,
                                display_name: a.display_name,
                                platform: a.platform,
                                dashboard_account_id: a.dashboard_account_id,
                                audience_count: a.audience_count,
                              });
                            }}
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
                              <path
                                d="M2 12C2 12 5.5 5 12 5C18.5 5 22 12 22 12C22 12 18.5 19 12 19C5.5 19 2 12 2 12Z"
                                stroke="currentColor"
                                strokeWidth="1.75"
                                strokeLinejoin="round"
                              />
                              <circle cx="12" cy="12" r="3.25" stroke="currentColor" strokeWidth="1.75" />
                            </svg>
                          </button>
                        ) : null}
                      </label>
                    );
                  })
                )}
              </div>
              {(bulkRunDetail?.items?.length ?? 0) > 0 ? (
                <button
                  type="button"
                  className="subs-btn subs-btn--muted"
                  style={{ width: "100%", marginBottom: 12, fontSize: 12 }}
                  onClick={() => setBulkRunDetailOpen(true)}
                >
                  Подробнее: очередь и слоты воркеров
                </button>
              ) : null}
              <div className="subs-modal-footer">
                <div style={{ fontSize: 13, color: "var(--ink-mute)", lineHeight: 1.45, minWidth: 0 }}>
                  К запуску:{" "}
                  <strong className="tnum" style={{ color: "var(--ink)" }}>
                    {bulkPickWillRunCount}
                  </strong>{" "}
                  из{" "}
                  <strong className="tnum" style={{ color: "var(--ink)" }}>
                    {bulkPickCount}
                  </strong>{" "}
                  выбранных
                </div>
                <div className="subs-modal-footer-actions">
                  <button type="button" className="subs-btn subs-btn--muted subs-btn--sm" onClick={() => setAudiencePickOpen(false)}>
                    Отмена
                  </button>
                  <button
                    type="button"
                    className="subs-btn-emphasis"
                    style={{ padding: "10px 18px", fontSize: 13 }}
                    disabled={bulkPickCount === 0 || bulkPickWillRunCount === 0}
                    onClick={() =>
                      void runBulk(
                        audiencePickSyncableAccounts.filter((a) => bulkSelectedIds.has(a.id)).map((a) => a.id),
                        audiencePickKind,
                      )
                    }
                  >
                    {audiencePickKind === "enrich" ? "Запустить обновление" : "Запустить сбор"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {membersPreviewAccount ? (
          <SubsMembersPreviewModal
            account={membersPreviewAccount}
            onClose={() => setMembersPreviewAccount(null)}
            fetchJson={fetchJson}
            subsApiBase={subsApi()}
            showToast={showToast}
            platformColor={PLATFORMS.find((p) => p.id === membersPreviewAccount.platform)?.color ?? "#9ca3af"}
            platformLabel={subsPlatformLabel(membersPreviewAccount.platform)}
            bulkBusy={bulkBusy}
            onRequestAudienceStop={requestAudienceStop}
          />
        ) : null}

        {csvPreviewOpen && (
          <div
            className="subs-modal-overlay"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 82,
              background: "rgba(0,0,0,0.82)",
              backdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            role="dialog"
            aria-modal
            aria-labelledby="subs-csv-preview-title"
            onClick={(e) => {
              if (e.target === e.currentTarget) setCsvPreviewOpen(false);
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              className="subs-modal-panel subs-modal-panel--wide"
              style={{
                maxWidth: "min(1100px, 100%)",
                width: "100%",
                maxHeight: "min(88vh, 720px)",
                overflow: "hidden",
                display: "flex",
                flexDirection: "column",
                borderRadius: 16,
                border: "1px solid var(--line-strong)",
                background: "var(--panel)",
                padding: 18,
                boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
              }}
            >
              <div
                className="subs-modal-toolbar"
                style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}
              >
                <div>
                  <h3 id="subs-csv-preview-title" style={{ margin: 0, fontSize: 16, color: "var(--ink)" }}>
                    Последний CSV
                  </h3>
                  {csvPreview?.generated_at ? (
                    <p className="subs-muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
                      Сформирован: {fmtDate(csvPreview.generated_at)}
                      {csvPreview.row_total != null ? (
                        <>
                          {" "}
                          · строк данных: <span className="tnum">{csvPreview.row_total}</span>
                        </>
                      ) : null}
                      {csvPreview.truncated ? " · в таблице показан фрагмент" : null}
                    </p>
                  ) : null}
                  {csvPreview?.query_string ? (
                    <p className="mono subs-muted" style={{ margin: "4px 0 0", fontSize: 10, wordBreak: "break-all" }}>
                      {csvPreview.query_string}
                    </p>
                  ) : null}
                </div>
                <div className="subs-modal-toolbar-actions">
                  <a
                    href={`${subsApi()}/api/subscribers/members/export/last.csv`}
                    className="subs-btn subs-btn--sm subs-btn--muted"
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
                    download
                  >
                    Скачать файл
                  </a>
                  <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={() => setCsvPreviewOpen(false)}>
                    Закрыть
                  </button>
                </div>
              </div>
              {csvPreviewLoading ? (
                <p style={{ margin: "18px 0", color: "var(--ink-dim)" }}>Загрузка…</p>
              ) : csvPreviewErr ? (
                <p style={{ margin: "18px 0", color: "var(--danger)" }}>{csvPreviewErr}</p>
              ) : csvPreview && csvPreview.headers.length ? (
                <div className="subs-csv-preview-scroll">
                  <table className="subs-table subs-csv-preview-table">
                    <thead>
                      <tr>
                        {csvPreview.headers.map((h, i) => (
                          <th key={`h-${i}`} className="mono" style={{ whiteSpace: "nowrap" }}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {csvPreview.rows.map((row, ri) => (
                        <tr key={`r-${ri}`}>
                          {row.map((cell, ci) => (
                            <td key={`c-${ri}-${ci}`} className="mono" style={{ maxWidth: 220, fontSize: 12 }}>
                              <span className="subs-csv-cell">{cell}</span>
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="subs-muted" style={{ margin: "18px 0" }}>
                  Нет данных.
                </p>
              )}
            </div>
          </div>
        )}

        {memberDeleteTarget && (
          <div
            className="subs-modal-overlay"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 80,
              background: "rgba(0,0,0,0.82)",
              backdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget && !memberDeleteBusy) setMemberDeleteTarget(null);
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              className="subs-modal-panel"
              style={{
                maxWidth: 440,
                width: "100%",
                borderRadius: 16,
                border: "1px solid var(--line-strong)",
                background: "var(--panel)",
                padding: 20,
                boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
              }}
            >
              <h3 style={{ margin: "0 0 10px", fontSize: 16, color: "var(--ink)" }}>Удалить из снятой базы?</h3>
              <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--ink-dim)", lineHeight: 1.45 }}>
                Подписчик{" "}
                <strong style={{ color: "var(--ink)" }}>@{memberDeleteTarget.username}</strong> (
                {memberDeleteTarget.platform}) будет убран из всех видимых отслеживаемых аккаунтов в subs и с
                дашборда (если для аккаунта задана связь). При следующем съёме запись может снова появиться, если
                человек всё ещё подписан.
              </p>
              <div className="subs-modal-actions">
                <button
                  type="button"
                  className="subs-btn subs-btn--muted subs-btn--sm"
                  disabled={memberDeleteBusy}
                  onClick={() => {
                    if (!memberDeleteBusy) setMemberDeleteTarget(null);
                  }}
                >
                  Отмена
                </button>
                <button
                  type="button"
                  className="subs-btn subs-btn--sm subs-btn--danger-text"
                  disabled={memberDeleteBusy}
                  onClick={async () => {
                    if (!memberDeleteTarget || memberDeleteBusy) return;
                    setMemberDeleteBusy(true);
                    try {
                      const delQs = buildSubscriberContextQuery().toString();
                      const out = (await fetchJson(
                        `${subsApi()}/api/subscribers/members/${memberDeleteTarget.id}/?${delQs}`,
                        { method: "DELETE" },
                      )) as { ok?: boolean; dashboard_errors?: string[] } | null;
                      const warnings =
                        out && Array.isArray(out.dashboard_errors) ? out.dashboard_errors : [];
                      setMemberDeleteTarget(null);
                      await reloadMembersAndOverview();
                      if (warnings.length) {
                        showToast(`Удалено. Предупреждения дашборда: ${warnings.join("; ")}`, true);
                      } else {
                        showToast("Подписчик удалён из снятой базы", false);
                      }
                    } catch (e) {
                      showToast(e instanceof Error ? e.message : String(e), true);
                    } finally {
                      setMemberDeleteBusy(false);
                    }
                  }}
                >
                  {memberDeleteBusy ? "…" : "Удалить"}
                </button>
              </div>
            </div>
          </div>
        )}

        {loadErr && <div className="subs-alert">{loadErr}</div>}

        <div className="subs-toolbar">
          <div className="subs-toolbar-row">
            <span className="mono subs-hint">Площадка</span>
            {(["all", ...PLATFORMS.map((x) => x.id)] as const).map((id) => {
              const meta = id === "all" ? undefined : PLATFORMS.find((p) => p.id === id);
              const active = filterPlatform === id;
              const label = id === "all" ? "Все" : meta?.label ?? id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setFilterPlatform(id)}
                  className={`subs-chip${active ? " subs-chip--active" : ""}`}
                >
                  {meta ? <span className="subs-dot" style={{ background: meta.color }} /> : null}
                  {label}
                </button>
              );
            })}
          </div>
          <div className="subs-toolbar-row">
            <span className="mono subs-hint">Профиль</span>
            <button
              type="button"
              onClick={() => setProfileFilter({ kind: "all" })}
              className={`subs-chip${profileFilter.kind === "all" ? " subs-chip--active" : ""}`}
              title="Все отслеживаемые аккаунты и подписчики"
            >
              Все
            </button>
            <button
              type="button"
              onClick={() => setProfileFilter({ kind: "none" })}
              className={`subs-chip${profileFilter.kind === "none" ? " subs-chip--active" : ""}`}
              title="Только аккаунты без привязки к профилю"
            >
              Без профиля
            </button>
            {subsProfiles.map((p) => {
              const selected =
                profileFilter.kind === "profiles" && profileFilter.ids.includes(p.id);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setProfileFilter((prev) => {
                      if (prev.kind === "none" || prev.kind === "all") {
                        return { kind: "profiles", ids: [p.id] };
                      }
                      const set = new Set(prev.ids);
                      if (set.has(p.id)) set.delete(p.id);
                      else set.add(p.id);
                      const arr = [...set].sort((a, b) => a - b);
                      if (arr.length === 0) return { kind: "all" };
                      return { kind: "profiles", ids: arr };
                    });
                  }}
                  className={`subs-chip${selected ? " subs-chip--active" : ""}`}
                  title="Повторный клик снимает. Несколько профилей — объединение: аккаунты и подписчики любого из выбранных"
                >
                  {p.name}
                </button>
              );
            })}
          </div>
          {profileFilter.kind === "profiles" && profileFilter.ids.length > 1 ? (
            <p className="subs-muted" style={{ margin: 0, fontSize: 12 }}>
              Выбрано профилей: {profileFilter.ids.length} — показаны аккаунты и подписчики по объединению.
            </p>
          ) : null}
        </div>

        {loading && !overview && <div className="subs-loading">Загрузка…</div>}

        {overview && s && (
          <>
            {subsMainView === "charts" ? (
              <section className="subs-charts-main" aria-labelledby="subs-charts-main-title">
                <div className="subs-charts-main-head">
                  <div>
                    <h2 id="subs-charts-main-title" className="mono" style={{ margin: 0, fontSize: 15, color: "var(--ink)" }}>
                      Графики
                      <span className="subs-muted" style={{ fontWeight: 400, fontSize: 13 }}>
                        {" "}
                        — по данным БД
                      </span>
                    </h2>
                    {presumedStats?.generated_at ? (
                      <p className="subs-muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
                        Расчёт: {fmtDate(presumedStats.generated_at)}
                        {presumedStats.member_row_count != null ? (
                          <>
                            {" "}
                            · учтено строк: <span className="tnum">{presumedStats.member_row_count}</span>
                          </>
                        ) : null}
                      </p>
                    ) : (
                      <p className="subs-muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
                        Диаграммы по колонкам «Предполагаемый …» для всех подписчиков в текущих фильтрах площадки и профиля (как у «Скачать CSV»).
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    className="subs-btn subs-btn--sm subs-btn--muted"
                    disabled={presumedStatsLoading}
                    onClick={() => void loadPresumedStats()}
                  >
                    {presumedStatsLoading ? "…" : "↻ Обновить"}
                  </button>
                </div>
                <div className="subs-charts-main-scroll subs-csv-preview-scroll subs-csv-charts-scroll">
                  <PresumedChartsPanel
                    data={presumedStats}
                    loading={presumedStatsLoading}
                    error={presumedStatsErr}
                    onRetry={() => void loadPresumedStats()}
                  />
                </div>
              </section>
            ) : (
              <>
            <div className="subs-columns">
              <section className="subs-col-left">
                <div className="subs-col-panel">
                  <div className="subs-col-panel-top">
                    <div className="mono subs-section-head">Отслеживаемые аккаунты</div>
                  </div>
                  <div className="subs-field-wrap">
                    <input
                      value={accountSearch}
                      onChange={(e) => setAccountSearch(e.target.value)}
                      placeholder="Поиск аккаунтов…"
                      className="subs-field"
                    />
                    <span className="subs-field-icon">⌕</span>
                  </div>
                  {accounts.length > 0 ? (
                    <div className="subs-meta-line">
                      Показано {pagedAccountsForTable.length} из {displayAccountsForTable.length}
                    </div>
                  ) : null}
                  {accounts.length === 0 ? (
                    <p className="subs-muted">Нет аккаунтов выбранных площадок в текущей выборке.</p>
                  ) : displayAccountsForTable.length === 0 ? (
                    <p className="subs-muted">
                      Нет аккаунтов по выбранной метрике. Повторный клик по той же карточке сверху снимает фильтр.
                    </p>
                  ) : (
                    <div className="subs-col-table-block">
                      <div className="subs-scroll">
                        <table className="subs-table">
                          <thead>
                            <tr>
                              <th>Площадка</th>
                              <th>Аккаунт</th>
                              <th style={{ textAlign: "right", whiteSpace: "nowrap" }}>Подписчики в БД</th>
                              <th>Съём</th>
                              <th style={{ whiteSpace: "nowrap" }}>Действия</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pagedAccountsForTable.map((a) => (
                              <tr key={a.id} className={membersFilterAccountId === a.id ? "subs-row-selected" : undefined}>
                                <td style={{ color: "var(--ink-dim)", fontSize: 12 }}>{a.platform}</td>
                                <td className="subs-table-name-col">
                                  <div className="subs-table-name-stack">
                                    <button
                                      type="button"
                                      className="subs-tracked-account-btn"
                                      title={
                                        membersFilterAccountId === a.id
                                          ? "Показать всех подписчиков"
                                          : "Показать только подписчиков этого аккаунта"
                                      }
                                      onClick={() =>
                                        setMembersFilterAccountId((cur) => (cur === a.id ? null : a.id))
                                      }
                                    >
                                      <div style={{ fontWeight: 600 }}>@{a.username}</div>
                                      {a.display_name ? (
                                        <div className="subs-table-name-secondary">{a.display_name}</div>
                                      ) : null}
                                    </button>
                                  </div>
                                </td>
                                <td style={{ textAlign: "right" }} className="tnum">
                                  {a.audience_count}
                                </td>
                                <td style={{ fontSize: 11, color: "var(--ink-dim)", whiteSpace: "nowrap" }}>
                                  {fmtDate(a.audience_last_synced_at)}
                                </td>
                                <td className="subs-table-actions-col">
                                  <div className="subs-table-actions-stack">
                                    <button
                                      type="button"
                                      disabled={refreshingId === a.id || bulkBusy || !a.dashboard_account_id}
                                      onClick={() => void runOne(a.id)}
                                      className="subs-btn-ghost"
                                      title={
                                        !a.dashboard_account_id
                                          ? "Сначала синхронизируйте с дашборда"
                                          : undefined
                                      }
                                    >
                                      {refreshingId === a.id ? "Сбор…" : "Собрать"}
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {accountTablePages > 1 ? (
                        <SubsPagerBar
                          page={accountTablePage}
                          totalPages={accountTablePages}
                          onPageChange={setAccountTablePage}
                        />
                      ) : null}
                    </div>
                  )}
                </div>
              </section>

              <section className="subs-col-right">
                <div className="subs-col-panel">
                  <div className="subs-col-panel-top">
                    <div className="subs-members-toolbar">
                      <div className="mono subs-section-head subs-section-head--toolbar">
                        {membersFilterAccountId != null
                          ? `Подписчики: ${membersFilterAccountLabel ?? "…"}`
                          : "Все подписчики (уникальные)"}
                      </div>
                      <div className="subs-members-toolbar-actions">
                        <button
                          type="button"
                          className="subs-btn subs-btn--sm subs-btn--muted"
                          disabled={exportCsvBusy || membersLoading}
                          title="Все подписчики по всем видимым отслеживаемым аккаунтам (площадка, профиль, поиск, карточки метрик). Выбранный слева аккаунт на состав файла не влияет."
                          onClick={() => void exportMembersCsv()}
                        >
                          {exportCsvBusy ? "…" : "Скачать CSV"}
                        </button>
                        <button
                          type="button"
                          className="subs-btn subs-btn--sm subs-btn--muted"
                          disabled={csvPreviewLoading}
                          title="Таблица из последнего успешного экспорта CSV (после «Скачать CSV»)"
                          onClick={() => void openLastCsvPreview()}
                        >
                          {csvPreviewLoading ? "…" : "Последний CSV"}
                        </button>
                      </div>
                    </div>
                    {membersFilterAccountId != null ? (
                      <div className="subs-members-filter-reset">
                        <button
                          type="button"
                          className="subs-btn subs-btn--sm subs-btn--muted"
                          onClick={() => setMembersFilterAccountId(null)}
                        >
                          Сбросить фильтр
                        </button>
                      </div>
                    ) : null}
                  </div>
                  <div className="subs-field-wrap">
                    <input
                      value={memberSearchInput}
                      onChange={(e) => setMemberSearchInput(e.target.value)}
                      placeholder="Поиск: ник, имя, био…"
                      className="subs-field"
                    />
                    <span className="subs-field-icon">⌕</span>
                  </div>
                  {membersErr ? <div className="subs-inline-err">{membersErr}</div> : null}
                  <div className="subs-meta-line">
                    {membersLoading ? "Загрузка списка…" : `Показано ${memberRows.length} из ${memberTotal}`}
                  </div>
                  <div className="subs-col-table-block">
                  <div className="subs-scroll">
                    <table className="subs-table">
                      <thead>
                        <tr>
                          <th>Площадка</th>
                          <th>Подписчик</th>
                          <th>Прив.</th>
                          <th style={{ textAlign: "right" }}>Наших акк.</th>
                          <th style={{ textAlign: "right", whiteSpace: "nowrap" }}>Действия</th>
                        </tr>
                      </thead>
                      <tbody>
                        {memberRows.map((m) => {
                          const href = profileUrl(m.platform, m.username);
                          return (
                            <tr key={m.id}>
                              <td style={{ color: "var(--ink-dim)", fontSize: 12 }}>{m.platform}</td>
                              <td className="subs-table-name-col">
                                <div className="subs-table-name-stack">
                                  <button
                                    type="button"
                                    className="subs-member-name-btn"
                                    onClick={() => setMemberCardId(m.id)}
                                    title="Подробности"
                                  >
                                    <span style={{ fontWeight: 600 }}>@{m.username}</span>
                                  </button>
                                  {m.display_name ? (
                                    <div className="subs-table-name-secondary">{m.display_name}</div>
                                  ) : null}
                                </div>
                              </td>
                              <td style={{ color: "var(--ink-dim)", fontSize: 12 }}>{m.is_private ? "да" : "нет"}</td>
                              <td
                                style={{ textAlign: "right", fontWeight: 600 }}
                                className={`tnum${m.follows_tracked_accounts > 1 ? " subs-num-hot" : ""}`}
                              >
                                {m.follows_tracked_accounts}
                              </td>
                              <td className="subs-table-actions-col">
                                <div className="subs-table-actions-stack">
                                  {href ? (
                                    <a href={href} target="_blank" rel="noreferrer" className="subs-link-out">
                                      Профиль
                                    </a>
                                  ) : null}
                                  {href ? <span style={{ display: "inline-block", width: 10 }} /> : null}
                                  <button
                                    type="button"
                                    className="subs-btn subs-btn--sm subs-btn--danger-text"
                                    disabled={memberDeleteBusy}
                                    onClick={() => setMemberDeleteTarget(m)}
                                  >
                                    Удалить
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <SubsPagerBar
                    page={memberPage}
                    totalPages={memberPages}
                    disabled={membersLoading}
                    onPageChange={setMemberPage}
                  />
                  </div>
                </div>
              </section>
            </div>

            </>
            )}
          </>
        )}
      </main>

      {bulkRunDetailOpen ? (
        <SubsBulkRunDetailOverlay detail={bulkRunDetail} onClose={() => setBulkRunDetailOpen(false)} />
      ) : null}
    </div>
  );
}
