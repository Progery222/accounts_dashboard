import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PresumedChartsPanel, type PresumedStatsResponse } from "./csvPresumedCharts";

const MEM_PAGE = 40;

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

/** База URL subs API. Через trycloudflare страница HTTPS — запросы только на тот же origin (/api…), Vite проксирует на :8010. */
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
    base = "http://127.0.0.1:8010";
  }
  if (typeof window !== "undefined" && window.location.protocol === "https:" && isHttpLoopbackApiBase(base)) {
    return "";
  }
  return base;
};

/** Основной React-дашборд (Vite): маршруты `/`, `/accounts/:id`, … */
const dashSpa = () =>
  (import.meta.env.VITE_DASHBOARD_SPA_URL || "http://localhost:5173").replace(/\/$/, "");

/** Atomic `app.html` (второй фронт): iframe «Авторизация» (`?route=settings`). */
const dashAtomic = () =>
  (
    import.meta.env.VITE_DASHBOARD_ATOMIC_URL ||
    import.meta.env.VITE_DASHBOARD_APP_URL ||
    "http://localhost:5174"
  ).replace(/\/$/, "");

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

/** Пауза между аккаунтами; прерывается при signal.aborted. */
async function sleepRandomMsUnlessCancelled(minMs: number, maxMs: number, signal: AbortSignal): Promise<void> {
  const total = Math.round(minMs + Math.random() * (maxMs - minMs));
  const deadline = Date.now() + total;
  while (Date.now() < deadline && !signal.aborted) {
    await new Promise<void>((r) => {
      window.setTimeout(r, Math.min(400, Math.max(0, deadline - Date.now())));
    });
  }
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
  top_subscribers: Array<{
    id: number;
    platform: string;
    username: string;
    display_name: string;
    is_private: boolean;
    follows_tracked_accounts: number;
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
type InsightMetricKey = "accounts" | "unique" | "private" | "with_data" | "synced";

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
/** Если метка давности не обновлялась — считаем, что вкладка сорвала сбор (закрыли). */
const SUBS_BULK_STALE_MS = 4 * 60 * 1000;

type SubsBulkStored = {
  v: 1;
  running: boolean;
  progress: BulkAudienceProgress | null;
  updatedAt: number;
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

function persistSubsBulkState(progress: BulkAudienceProgress | null): void {
  try {
    const payload: SubsBulkStored = { v: 1, running: true, progress, updatedAt: Date.now() };
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

export default function App() {
  const [narrow, setNarrow] = useState(false);
  const [mainTab, setMainTab] = useState<"subscribers" | "auth">("subscribers");
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
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkSelectedIds, setBulkSelectedIds] = useState<Set<number>>(() => new Set());
  /** Пустой массив = все площадки; иначе аккаунт попадает в список, если platform в наборе. */
  const [bulkModalPlatforms, setBulkModalPlatforms] = useState<string[]>([]);
  /** Пустой массив = все профили; иначе OR по ключам: "none" (без профиля) или "id:123". */
  const [bulkModalProfileKeys, setBulkModalProfileKeys] = useState<string[]>([]);
  const [bulkSkipExistingMemberProfiles, setBulkSkipExistingMemberProfiles] = useState(false);
  /** Прерывание массового сбора (пауза между аккаунтами и активные fetch). */
  const bulkAbortRef = useRef<AbortController | null>(null);
  /** true только в той вкладке, где выполняется runBulk (не зеркалировать своё же localStorage). */
  const bulkRunActiveInThisTabRef = useRef(false);
  const [bulkRemoteView, setBulkRemoteView] = useState(false);
  const [subsProfiles, setSubsProfiles] = useState<Array<{ id: number; name: string }>>([]);
  const [syncBusy, setSyncBusy] = useState(false);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);
  const [csvPreviewOpen, setCsvPreviewOpen] = useState(false);
  const [csvPreviewLoading, setCsvPreviewLoading] = useState(false);
  const [csvPreviewErr, setCsvPreviewErr] = useState<string | null>(null);
  const [csvPreview, setCsvPreview] = useState<CsvLastPreview | null>(null);
  const [csvPreviewSubview, setCsvPreviewSubview] = useState<"table" | "charts">("table");
  const [presumedStats, setPresumedStats] = useState<PresumedStatsResponse | null>(null);
  const [presumedStatsLoading, setPresumedStatsLoading] = useState(false);
  const [presumedStatsErr, setPresumedStatsErr] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; isErr: boolean } | null>(null);

  const showToast = (msg: string, isErr: boolean) => {
    setToast({ msg, isErr });
    window.setTimeout(() => setToast(null), 4200);
  };

  const requestBulkStop = useCallback(() => {
    bulkAbortRef.current?.abort();
    try {
      const bc = new BroadcastChannel(SUBS_BULK_BC_NAME);
      bc.postMessage({ type: "bulk-abort" });
      bc.close();
    } catch {
      /* */
    }
  }, []);

  useEffect(() => {
    const bc = new BroadcastChannel(SUBS_BULK_BC_NAME);
    bc.onmessage = (ev: MessageEvent<{ type?: string }>) => {
      if (ev.data?.type === "bulk-abort") bulkAbortRef.current?.abort();
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
        return;
      }
      const s = parsed as Partial<SubsBulkStored>;
      if (s.v !== 1 || !s.running) {
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        return;
      }
      const updatedAt = typeof s.updatedAt === "number" ? s.updatedAt : 0;
      if (Date.now() - updatedAt > SUBS_BULK_STALE_MS) {
        clearSubsBulkState();
        setBulkBusy(false);
        setBulkAudienceProgress(null);
        setBulkRemoteView(false);
        return;
      }
      setBulkBusy(true);
      setBulkAudienceProgress(s.progress != null && isBulkProgressValue(s.progress) ? s.progress : null);
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
          return;
        }
        const parsed = JSON.parse(raw) as Partial<SubsBulkStored>;
        if (parsed.v !== 1 || !parsed.running || typeof parsed.updatedAt !== "number") {
          setBulkBusy(false);
          setBulkAudienceProgress(null);
          setBulkRemoteView(false);
          return;
        }
        if (Date.now() - parsed.updatedAt > SUBS_BULK_STALE_MS) {
          clearSubsBulkState();
          setBulkBusy(false);
          setBulkAudienceProgress(null);
          setBulkRemoteView(false);
          return;
        }
        if (parsed.progress != null && isBulkProgressValue(parsed.progress)) {
          setBulkAudienceProgress(parsed.progress);
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
      p.set("top_limit", "60");
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
      setLoadErr(e instanceof Error ? e.message : String(e));
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
    qs.set("page_size", String(MEM_PAGE));
    if (memberSearch) qs.set("search", memberSearch);
    if (membersFilterAccountId != null) qs.set("for_account", String(membersFilterAccountId));
    if (insightMetric === "private") qs.set("only_private", "1");
    if (insightMetric === "unique") qs.set("member_sort", "follows_desc");
    return qs;
  }, [buildSubscriberContextQuery, memberPage, memberSearch, membersFilterAccountId, insightMetric]);

  const buildMembersExportQuery = useCallback(() => {
    const qs = buildSubscriberContextQuery();
    if (memberSearch) qs.set("search", memberSearch);
    if (membersFilterAccountId != null) qs.set("for_account", String(membersFilterAccountId));
    if (insightMetric === "private") qs.set("only_private", "1");
    if (insightMetric === "unique") qs.set("member_sort", "follows_desc");
    return qs;
  }, [buildSubscriberContextQuery, memberSearch, membersFilterAccountId, insightMetric]);

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
    const qs = buildMembersExportQuery();
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
    setCsvPreviewSubview("table");
    setPresumedStats(null);
    setPresumedStatsErr(null);
    setPresumedStatsLoading(false);
    await fetchLastExportPreview();
  };

  const openLastCsvPresumedCharts = () => {
    setCsvPreviewOpen(true);
    setCsvPreviewSubview("charts");
    setPresumedStats(null);
    setPresumedStatsErr(null);
    setCsvPreview(null);
    setCsvPreviewErr(null);
    void fetchLastExportPreview();
    void loadPresumedStats();
  };

  const loadPresumedStats = async () => {
    setPresumedStatsLoading(true);
    setPresumedStatsErr(null);
    try {
      const d = (await fetchJson(
        `${subsApi()}/api/subscribers/members/export/last/presumed-stats/`,
      )) as PresumedStatsResponse;
      setPresumedStats(d);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setPresumedStatsErr(msg);
      showToast(msg, true);
    } finally {
      setPresumedStatsLoading(false);
    }
  };

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
    const uname = overview?.accounts?.find((x) => x.id === subsAccountId)?.username ?? null;
    setSingleAudienceUsername(uname);
    setRefreshingId(subsAccountId);
    try {
      await fetchJson(`${subsApi()}/api/subscribers/sync/account/${subsAccountId}/audience/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skip_existing_member_profiles: bulkSkipExistingMemberProfiles,
        }),
      });
      showToast("Съём и импорт подписчиков выполнены", false);
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), true);
    } finally {
      setRefreshingId(null);
      setSingleAudienceUsername(null);
    }
  };

  const runBulk = async (selectedIds: number[]) => {
    const rows = overview?.accounts ?? [];
    if (!rows.length) return;
    const idSet = new Set(selectedIds);
    const syncable = rows.filter((a) => idSet.has(a.id) && a.dashboard_account_id);
    if (!syncable.length) {
      showToast("Нет выбранных аккаунтов с привязкой к дашборду.", true);
      return;
    }
    bulkAbortRef.current?.abort();
    const ac = new AbortController();
    bulkAbortRef.current = ac;
    const signal = ac.signal;
    bulkRunActiveInThisTabRef.current = true;
    setBulkRemoteView(false);

    setBulkModalOpen(false);
    setBulkBusy(true);
    setBulkAudienceProgress(null);
    persistSubsBulkState(null);
    let ok = 0;
    let fail = 0;
    const total = syncable.length;
    try {
      for (let i = 0; i < syncable.length; i += 1) {
        if (signal.aborted) break;
        const a = syncable[i];
        const progAccount: BulkAudienceProgress = {
          total,
          current: i + 1,
          username: a.username,
          phase: "account",
        };
        setBulkAudienceProgress(progAccount);
        persistSubsBulkState(progAccount);
        try {
          await fetchJson(`${subsApi()}/api/subscribers/sync/account/${a.id}/audience/`, {
            method: "POST",
            signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              skip_existing_member_profiles: bulkSkipExistingMemberProfiles,
            }),
          });
          ok += 1;
        } catch (e) {
          if (signal.aborted || (e instanceof DOMException && e.name === "AbortError")) break;
          fail += 1;
        }
        if (signal.aborted) break;
        if (i < syncable.length - 1) {
          const next = syncable[i + 1];
          const progPause: BulkAudienceProgress = {
            total,
            current: i + 2,
            username: next.username,
            phase: "pause",
          };
          setBulkAudienceProgress(progPause);
          persistSubsBulkState(progPause);
          await sleepRandomMsUnlessCancelled(5000, 9000, signal);
          if (signal.aborted) break;
        }
      }

      if (!signal.aborted) {
        const progCsv: BulkAudienceProgress = {
          total,
          current: total,
          username: "",
          phase: "csv",
        };
        setBulkAudienceProgress(progCsv);
        persistSubsBulkState(progCsv);
        const omitted = rows.filter((a) => a.dashboard_account_id && !idSet.has(a.id)).length;
        const parts = [`успешно ${ok}`, `ошибок ${fail}`];
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
          if (!signal.aborted && !(e instanceof DOMException && e.name === "AbortError")) {
            serverCsvNote = ` Отчёт на сервере не обновлён: ${e instanceof Error ? e.message : String(e)}`;
          }
        }
        if (!signal.aborted) {
          showToast(`Готово: ${parts.join(", ")}${serverCsvNote}`, fail > 0 || Boolean(serverCsvNote));
        }
      }
      if (signal.aborted) {
        showToast(
          ok > 0 || fail > 0
            ? `Сбор остановлен. Успешно: ${ok}, ошибок: ${fail}. Отчёт CSV на сервере не обновляли.`
            : "Сбор отменён до обработки аккаунтов.",
          false,
        );
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
  const top = overview?.top_subscribers ?? [];

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

  const bulkPickCount = useMemo(
    () => bulkModalSyncableAccounts.filter((a) => bulkSelectedIds.has(a.id)).length,
    [bulkModalSyncableAccounts, bulkSelectedIds],
  );

  useEffect(() => {
    if (!bulkModalOpen) return;
    setBulkSelectedIds((prev) => new Set([...prev].filter((id) => bulkModalAccounts.some((a) => a.id === id))));
  }, [bulkModalOpen, bulkModalAccounts]);

  useEffect(() => {
    if (!bulkModalOpen || bulkBusy) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") setBulkModalOpen(false);
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [bulkModalOpen, bulkBusy]);

  useEffect(() => {
    if (!csvPreviewOpen) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCsvPreviewOpen(false);
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [csvPreviewOpen]);

  useEffect(() => {
    if (!csvPreviewOpen) {
      setCsvPreviewSubview("table");
      setPresumedStats(null);
      setPresumedStatsErr(null);
      setPresumedStatsLoading(false);
    }
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
    } else if (insightMetric === "synced") {
      rows = rows.filter((a) => !!a.audience_last_synced_at);
    }
    rows = [...rows];
    if (insightMetric === "accounts") {
      rows.sort((a, b) => a.username.localeCompare(b.username, "ru"));
    } else if (insightMetric === "unique" || insightMetric === "with_data" || insightMetric === "synced") {
      rows.sort((a, b) => (b.audience_count || 0) - (a.audience_count || 0));
    }
    return rows;
  }, [filteredAccounts, insightMetric]);

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
  const memberPages = Math.max(1, Math.ceil(memberTotal / MEM_PAGE));
  const memberRows = membersData?.results ?? [];

  return (
    <div className="subs-shell">
      <header className="subs-header">
        <div className="subs-header-row">
          <div>
            <div className="mono subs-brand-kicker">SUBS</div>
            <div className="subs-brand-title">Подписчики</div>
          </div>
          <div
            className={`subs-header-actions${mainTab === "subscribers" ? " subs-header-actions--subscribers" : ""}`}
          >
            <div className="subs-segment-group">
              {(
                [
                  ["subscribers", "Подписчики"],
                  ["auth", "Авторизация"],
                ] as const
              ).map(([id, label]) => {
                const active = mainTab === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setMainTab(id)}
                    className={`subs-segment${active ? " subs-segment--active" : ""}`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {mainTab === "subscribers" ? (
              <>
                <button
                  type="button"
                  onClick={() => void syncFromDashboard()}
                  disabled={syncBusy}
                  className="subs-btn subs-btn--sync"
                >
                  {syncBusy ? "…" : "Синхр. с дашборда"}
                </button>
                <button
                  type="button"
                  onClick={() => void load()}
                  disabled={loading}
                  className="subs-btn subs-btn--muted subs-btn--refresh"
                >
                  {loading ? "…" : "↻ Обновить"}
                </button>
                <button
                  type="button"
                  className="subs-btn subs-btn--muted subs-btn--charts"
                  disabled={presumedStatsLoading}
                  title="Диаграммы по колонкам «Предполагаемый …» из полного последнего CSV (после «Скачать CSV»)"
                  onClick={() => openLastCsvPresumedCharts()}
                >
                  {presumedStatsLoading ? "…" : "Графики"}
                </button>
              </>
            ) : null}
            <a href={`${dashSpa()}/`} className="subs-btn subs-btn--dash">
              Дашборд
            </a>
          </div>
        </div>
      </header>

      <main className="subs-main" data-layout={mainTab === "auth" ? "auth" : "subscribers"}>
        {mainTab === "auth" ? (
          <div className="subs-auth-wrap">
            <p className="subs-auth-note">
              Страница настроек дашборда (соцсети). Нужен atomic-фронт{" "}
              <span className="mono">{dashAtomic()}</span>
              <span className="mono">/app.html</span> (см. <span className="mono">VITE_DASHBOARD_ATOMIC_URL</span>).
            </p>
            <iframe
              title="Авторизация дашборда"
              src={`${dashAtomic()}/app.html?route=settings`}
              className="subs-iframe"
            />
          </div>
        ) : null}

        {toast && (
          <div className={`subs-banner ${toast.isErr ? "subs-banner--err" : "subs-banner--ok"}`}>{toast.msg}</div>
        )}

        {bulkBusy ? (
          <div className="subs-collect-dock" role="status" aria-live="polite">
            {bulkAudienceProgress ? (
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
                      className="subs-btn subs-btn--sm subs-btn--danger-text"
                      onClick={requestBulkStop}
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
                  <span className="subs-collect-dock-title">Сбор подписчиков</span>
                  <button
                    type="button"
                    className="subs-btn subs-btn--sm subs-btn--danger-text"
                    style={{ marginLeft: "auto", flexShrink: 0 }}
                    onClick={requestBulkStop}
                  >
                    Остановить
                  </button>
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
              <div className="subs-collect-dock-row">
                <span className="subs-collect-dock-title">Сбор подписчиков</span>
                <span className="subs-collect-dock-counter mono">1 / 1</span>
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
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
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

        {bulkModalOpen && !bulkBusy && (
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
              if (e.target === e.currentTarget) setBulkModalOpen(false);
            }}
          >
            <div
              role="dialog"
              aria-modal
              aria-labelledby="subs-bulk-modal-title"
              className="subs-modal-panel"
              onClick={(e) => e.stopPropagation()}
              style={{
                maxWidth: 520,
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
              <h3 id="subs-bulk-modal-title" style={{ margin: "0 0 8px", fontSize: 17, color: "var(--ink)" }}>
                Сбор подписчиков
              </h3>
              <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--ink-dim)", lineHeight: 1.45 }}>
                Отметьте аккаунты для съёма через дашборд. Между запусками сохраняется пауза 5–9 с. Аккаунты без связи с
                дашбордом недоступны — сначала «Синхр. с дашборда». Фильтры ниже сужают только список в этом окне. Можно
                выбрать несколько площадок и несколько профилей; если в блоке ничего не выбрано — подразумевается «все».
              </p>
              <div style={{ marginBottom: 12 }}>
                <div className="mono subs-hint" style={{ marginBottom: 6 }}>
                  Площадка
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
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
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
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
              <label
                title="Действует и для «Собрать» у отдельного аккаунта в таблице, и для массового сбора."
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
                  checked={bulkSkipExistingMemberProfiles}
                  onChange={(e) => setBulkSkipExistingMemberProfiles(e.target.checked)}
                  style={{ marginTop: 3, flexShrink: 0 }}
                />
                <span>
                  Пропускать уже сохранённых подписчиков: не открывать их профили на дашборде (быстрее, меньше
                  срабатываний антибота). Новые по-прежнему снимаются полностью.
                </span>
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
                <button
                  type="button"
                  className="subs-btn subs-btn--sm subs-btn--muted"
                  onClick={() => setBulkSelectedIds(new Set(bulkModalSyncableAccounts.map((a) => a.id)))}
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
                {bulkModalAccounts.length === 0 ? (
                  <p className="subs-muted" style={{ margin: 8 }}>
                    Нет аккаунтов по текущим фильтрам.
                  </p>
                ) : (
                  bulkModalAccounts.map((a) => {
                    const can = !!a.dashboard_account_id;
                    const checked = bulkSelectedIds.has(a.id);
                    const meta = PLATFORMS.find((p) => p.id === a.platform);
                    return (
                      <label
                        key={a.id}
                        className="subs-bulk-pick-row"
                        style={{
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 10,
                          padding: "10px 8px",
                          borderRadius: 10,
                          cursor: can ? "pointer" : "default",
                          opacity: can ? 1 : 0.55,
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
                          {!can ? (
                            <span style={{ display: "block", fontSize: 11, color: "var(--ink-dim)", marginTop: 4 }}>
                              Нет связи с дашбордом
                            </span>
                          ) : null}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <span className="subs-muted" style={{ fontSize: 13 }}>
                  К запуску: <strong className="tnum">{bulkPickCount}</strong> из {bulkModalSyncableAccounts.length}
                </span>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button type="button" className="subs-btn subs-btn--muted subs-btn--sm" onClick={() => setBulkModalOpen(false)}>
                    Отмена
                  </button>
                  <button
                    type="button"
                    className="subs-btn-emphasis"
                    style={{ padding: "10px 18px", fontSize: 13 }}
                    disabled={bulkPickCount === 0}
                    onClick={() =>
                      void runBulk(
                        bulkModalSyncableAccounts.filter((a) => bulkSelectedIds.has(a.id)).map((a) => a.id),
                      )
                    }
                  >
                    Запустить сбор
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

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
                maxHeight: csvPreviewSubview === "charts" ? "min(92vh, 900px)" : "min(88vh, 720px)",
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
                    {csvPreviewSubview === "charts" ? (
                      <span className="subs-muted" style={{ fontWeight: 400, fontSize: 13 }}>
                        {" "}
                        — графики
                      </span>
                    ) : null}
                  </h3>
                  {csvPreviewSubview === "charts" && presumedStats?.generated_at ? (
                    <p className="subs-muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
                      Сформирован: {fmtDate(presumedStats.generated_at)}
                    </p>
                  ) : null}
                  {csvPreviewSubview !== "charts" && csvPreview?.generated_at ? (
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
                  {csvPreviewSubview !== "charts" && csvPreview?.query_string ? (
                    <p className="mono subs-muted" style={{ margin: "4px 0 0", fontSize: 10, wordBreak: "break-all" }}>
                      {csvPreview.query_string}
                    </p>
                  ) : null}
                </div>
                <div style={{ display: "flex", gap: 8, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <a
                    href={`${subsApi()}/api/subscribers/members/export/last.csv`}
                    className="subs-btn subs-btn--sm subs-btn--muted"
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
                    download
                  >
                    Скачать файл
                  </a>
                  {csvPreviewSubview === "charts" ? (
                    <button
                      type="button"
                      className="subs-btn subs-btn--sm subs-btn--muted"
                      disabled={presumedStatsLoading}
                      onClick={() => setCsvPreviewSubview("table")}
                    >
                      Таблица
                    </button>
                  ) : null}
                  <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={() => setCsvPreviewOpen(false)}>
                    Закрыть
                  </button>
                </div>
              </div>
              {csvPreviewSubview === "charts" ? (
                <div className="subs-csv-preview-scroll subs-csv-charts-scroll">
                  <PresumedChartsPanel
                    data={presumedStats}
                    loading={presumedStatsLoading}
                    error={presumedStatsErr}
                    onRetry={() => void loadPresumedStats()}
                  />
                </div>
              ) : csvPreviewLoading ? (
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
              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
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

        {mainTab === "subscribers" && (
          <>
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
            <div className="subs-metrics">
              {(
                [
                  ["Аккаунтов", fmtNum(s.tracked_accounts_count), "accounts" as const, "Сортировка по нику"],
                  ["Уникальных", fmtNum(s.unique_subscribers_total), "unique" as const, "Подписчики: по числу наших аккаунтов"],
                  ["Приватных", fmtNum(s.private_subscribers_total), "private" as const, "Только закрытые профили"],
                  ["С данными", fmtNum(s.accounts_with_audience_rows), "with_data" as const, "Аккаунты с подписчиками в базе"],
                  ["Уже съём", fmtNum(s.accounts_synced_at_least_once), "synced" as const, "Аккаунты с датой последнего съёма"],
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
                    onClick={() => toggleInsightMetric(key)}
                    className={`subs-metric subs-metric--btn${accent ? " subs-metric--accent" : ""}${active ? " subs-metric--active" : ""}`}
                  >
                    <div className="mono subs-metric-label">{label}</div>
                    <div className="subs-metric-value tnum">{value}</div>
                  </button>
                );
              })}
            </div>

            <div className="subs-columns">
              <section className="subs-col-left">
                <div className="subs-panel">
                  <div className="subs-panel-title">Собрать подписчиков</div>
                  <p className="subs-panel-text">
                    Съём через API дашборда и импорт в БД subs. Сначала «Синхр. с дашборда», затем авторизация площадок на
                    вкладке «Авторизация».
                  </p>
                  <button
                    type="button"
                    disabled={bulkBusy || loading || !syncableAccounts.length}
                    onClick={() => {
                      if (!syncableAccounts.length) {
                        showToast("Нет аккаунтов с привязкой к дашборду — сначала «Синхр. с дашборда»", true);
                        return;
                      }
                      setBulkModalPlatforms([]);
                      setBulkModalProfileKeys([]);
                      setBulkSelectedIds(new Set(syncableAccounts.map((a) => a.id)));
                      setBulkModalOpen(true);
                    }}
                    className="subs-btn-emphasis"
                  >
                    {bulkBusy ? "Сбор…" : `Собрать для всех… (${syncableAccounts.length})`}
                  </button>
                </div>

                <div>
                  <div className="mono subs-section-head">Отслеживаемые аккаунты</div>
                  <div className="subs-field-wrap">
                    <input
                      value={accountSearch}
                      onChange={(e) => setAccountSearch(e.target.value)}
                      placeholder="Поиск аккаунтов…"
                      className="subs-field"
                    />
                    <span className="subs-field-icon">⌕</span>
                  </div>
                  {accounts.length === 0 ? (
                    <p className="subs-muted">Нет аккаунтов выбранных площадок в текущей выборке.</p>
                  ) : displayAccountsForTable.length === 0 ? (
                    <p className="subs-muted">
                      Нет аккаунтов по выбранной метрике. Повторный клик по той же карточке сверху снимает фильтр.
                    </p>
                  ) : (
                    <div className="subs-scroll">
                      <table className="subs-table">
                        <thead>
                          <tr>
                            <th>Площадка</th>
                            <th>Аккаунт</th>
                            <th style={{ textAlign: "right", whiteSpace: "nowrap" }}>В базе</th>
                            <th>Съём</th>
                            <th style={{ whiteSpace: "nowrap" }}>Действия</th>
                          </tr>
                        </thead>
                        <tbody>
                          {displayAccountsForTable.map((a) => (
                            <tr key={a.id} className={membersFilterAccountId === a.id ? "subs-row-selected" : undefined}>
                              <td style={{ color: "var(--ink-dim)", fontSize: 12 }}>{a.platform}</td>
                              <td>
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
                                    <div style={{ fontSize: 11, color: "var(--ink-mute)" }}>{a.display_name}</div>
                                  ) : null}
                                </button>
                              </td>
                              <td style={{ textAlign: "right" }} className="tnum">
                                {a.audience_count}
                              </td>
                              <td style={{ fontSize: 11, color: "var(--ink-dim)", whiteSpace: "nowrap" }}>
                                {fmtDate(a.audience_last_synced_at)}
                              </td>
                              <td style={{ whiteSpace: "nowrap" }}>
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
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </section>

              <section className="subs-col-right">
                <div style={{ width: "100%" }}>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 10,
                      marginBottom: 8,
                    }}
                  >
                    <div className="mono subs-section-head" style={{ marginBottom: 0 }}>
                      {membersFilterAccountId != null
                        ? `Подписчики: ${membersFilterAccountLabel ?? "…"}`
                        : "Все подписчики (уникальные)"}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <button
                        type="button"
                        className="subs-btn subs-btn--sm subs-btn--muted"
                        disabled={exportCsvBusy || membersLoading}
                        title="Все строки по текущим фильтрам (площадка, профиль, поиск, аккаунт слева, карточки метрик)"
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
                    <div style={{ marginBottom: 10 }}>
                      <button
                        type="button"
                        className="subs-btn subs-btn--sm subs-btn--muted"
                        onClick={() => setMembersFilterAccountId(null)}
                      >
                        Сбросить фильтр
                      </button>
                    </div>
                  ) : null}
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
                              <td>
                                <button
                                  type="button"
                                  className="subs-member-name-btn"
                                  onClick={() => setMemberCardId(m.id)}
                                  title="Подробности"
                                >
                                  <span style={{ fontWeight: 600 }}>@{m.username}</span>
                                </button>
                                {m.display_name ? (
                                  <div style={{ fontSize: 11, color: "var(--ink-mute)" }}>{m.display_name}</div>
                                ) : null}
                              </td>
                              <td style={{ color: "var(--ink-dim)", fontSize: 12 }}>{m.is_private ? "да" : "нет"}</td>
                              <td
                                style={{ textAlign: "right", fontWeight: 600 }}
                                className={`tnum${m.follows_tracked_accounts > 1 ? " subs-num-hot" : ""}`}
                              >
                                {m.follows_tracked_accounts}
                              </td>
                              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
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
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {memberTotal > MEM_PAGE ? (
                    <div className="subs-pager">
                      <button
                        type="button"
                        disabled={memberPage <= 1 || membersLoading}
                        onClick={() => setMemberPage((p) => Math.max(1, p - 1))}
                        className="subs-btn subs-btn--sm subs-btn--muted"
                        style={{ opacity: memberPage <= 1 ? 0.45 : 1 }}
                      >
                        Назад
                      </button>
                      <span className="mono tnum subs-mono-note">
                        Стр. {memberPage} / {memberPages}
                      </span>
                      <button
                        type="button"
                        disabled={memberPage >= memberPages || membersLoading}
                        onClick={() => setMemberPage((p) => Math.min(memberPages, p + 1))}
                        className="subs-btn subs-btn--sm subs-btn--muted"
                        style={{ opacity: memberPage >= memberPages ? 0.45 : 1 }}
                      >
                        Вперёд
                      </button>
                    </div>
                  ) : null}
                </div>
              </section>
            </div>

            <div className="subs-top-block">
              <div className="mono subs-section-head">Топ пересечений</div>
              {top.length === 0 ? (
                <p className="subs-muted">Пока пусто — сначала соберите аудиторию.</p>
              ) : (
                <div className="subs-scroll" style={{ maxHeight: "none" }}>
                  <table className="subs-table">
                    <thead>
                      <tr>
                        <th style={{ width: 36 }}>#</th>
                        <th>Ник</th>
                        <th>Прив.</th>
                        <th style={{ textAlign: "right" }}>Наших акк.</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {top.slice(0, 20).map((m, idx) => {
                        const href = profileUrl(m.platform, m.username);
                        return (
                          <tr key={m.id}>
                            <td style={{ color: "var(--ink-mute)" }}>{idx + 1}</td>
                            <td>
                              <button
                                type="button"
                                className="subs-member-name-btn"
                                onClick={() => setMemberCardId(m.id)}
                                title="Подробности"
                              >
                                <span style={{ fontWeight: 600 }}>@{m.username}</span>
                              </button>
                            </td>
                            <td style={{ color: "var(--ink-dim)" }}>{m.is_private ? "да" : "нет"}</td>
                            <td style={{ textAlign: "right", fontWeight: 700 }} className="tnum subs-num-hot">
                              {m.follows_tracked_accounts}
                            </td>
                            <td>
                              {href ? (
                                <a href={href} target="_blank" rel="noreferrer" className="subs-link-out">
                                  Профиль
                                </a>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
          </>
        )}
      </main>
    </div>
  );
}
