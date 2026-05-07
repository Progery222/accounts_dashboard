import { useState, useDeferredValue, useRef, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import {
  getAccounts, getPlatforms, createAccount, deleteAccount,
  refreshAccount,
  refreshAccountsBulk,
  getSchedule, setSchedule, getAutoRefreshStatus, runAutoRefreshNow, stopAutoRefresh,
  downloadAutoRefreshReport,
  getGlobalVisibility, setGlobalVisibility,
  downloadSnapshotExport, importSnapshotFile,
  type Account, type Platform, type RefreshSchedule, type AutoRefreshStatus,
} from "../api/accounts";
import {
  getProfiles, createProfile, updateProfile, deleteProfile,
  type Profile, type ProfileInput,
} from "../api/profiles";
import Analytics from "./Analytics";
import PlatformIcon from "../components/PlatformIcon";

type Tab = "accounts" | "analytics";
type SortKey = "follower_count" | "view_count" | "like_count" | "post_count" | "updated_at";
type SortOrder = "asc" | "desc";
type AvailabilityMainFilter = "all" | "available" | "unavailable";
type RefreshStatusLabel = "обновилось" | "нет обновлений" | "ошибка";
type RefreshReportRow = {
  id: number;
  platform: string;
  username: string;
  status: RefreshStatusLabel;
  follower_count: number;
  follower_delta: number | null;
  like_count: number;
  like_delta: number | null;
  view_count: number;
  view_delta: number | null;
  post_count: number;
  post_delta: number | null;
  error?: string;
};

// ── helpers ───────────────────────────────────────────────────────────────────

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

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function displayHandle(platform: string, username: string): string {
  return platform === "rumble" ? username : `@${username}`;
}

function refreshErrorsCountRu(n: number): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} ошибка`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} ошибки`;
  return `${n} ошибок`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Общее время массового обновления (секунды) → фраза для подписи в шапке. */
function formatRefreshTotalDurationRu(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "за 0 с";
  if (sec < 60) {
    const rounded = Math.round(sec * 10) / 10;
    const s = Number.isInteger(rounded) ? String(Math.round(rounded)) : rounded.toFixed(1);
    return `за ${s} с`;
  }
  const min = Math.floor(sec / 60);
  const rem = Math.round(sec - min * 60);
  if (rem <= 0) return `за ${min} мин`;
  if (rem === 60) return `за ${min + 1} мин`;
  return `за ${min} мин ${rem} с`;
}

// ── Compact stat pill ─────────────────────────────────────────────────────────

function StatPill({ label, value, delta }: { label: string; value: number; delta?: number | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-zinc-500 text-xs">{label}</span>
      <div className="flex items-center gap-1.5">
        <span className="text-white font-semibold text-sm">{fmt(value)}</span>
        {delta != null && delta !== 0 && (
          <span className={`text-xs font-medium ${delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
            {fmtDelta(delta)}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Preset colours for profile picker ────────────────────────────────────────

const PRESET_COLORS = [
  "#6366f1","#8b5cf6","#ec4899","#ef4444",
  "#f97316","#eab308","#22c55e","#14b8a6","#3b82f6","#64748b",
];

// ── Profile sidebar ───────────────────────────────────────────────────────────

function ProfileSidebar({
  profiles,
  selected,
  onSelect,
  onToggleHidden,
}: {
  profiles: Profile[];
  selected: number | "none" | null;
  onSelect: (v: number | "none" | null) => void;
  onToggleHidden: (profileId: number) => void;
}) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deletingProfile, setDeletingProfile] = useState<Profile | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["profiles"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
  };

  const createMutation = useMutation({
    mutationFn: createProfile,
    onSuccess: () => { invalidate(); setShowCreate(false); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ProfileInput> }) => updateProfile(id, data),
    onSuccess: () => { invalidate(); setEditingId(null); },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, deleteAccounts }: { id: number; deleteAccounts: boolean }) =>
      deleteProfile(id, deleteAccounts),
    onSuccess: (_, vars) => {
      invalidate();
      setDeletingProfile(null);
      // If the deleted profile was selected, reset filter
      if (selected === vars.id) onSelect(null);
    },
  });

  const filtered = profiles.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <aside className="w-56 shrink-0 flex flex-col gap-1">
      {/* Search + create */}
      <div className="flex gap-1.5 mb-2">
        <div className="relative flex-1">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
          </svg>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск профилей"
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-8 pr-2 py-1.5 text-xs text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
          />
        </div>
        <button
          onClick={() => { setShowCreate(v => !v); setEditingId(null); }}
          title="Создать профиль"
          className="w-7 h-7 flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white transition-colors shrink-0 text-base leading-none"
        >+</button>
      </div>

      {/* Create form */}
      {showCreate && (
        <ProfileInlineForm
          initial={{ name: "", description: "", color: "#6366f1", avatar_url: "" }}
          onSave={data => createMutation.mutate(data)}
          onCancel={() => setShowCreate(false)}
          loading={createMutation.isPending}
        />
      )}

      {/* Static items */}
      <SidebarItem active={selected === null}   onClick={() => onSelect(null)}   label="Все профили"  count={profiles.reduce((s, p) => s + p.account_count, 0)} color={null} />
      <SidebarItem active={selected === "none"} onClick={() => onSelect("none")} label="Без профиля" count={null} color={null} muted />

      {/* Profile list */}
      {filtered.length > 0 && (
        <div className="border-t border-zinc-800 my-1 pt-1 flex flex-col gap-0.5">
          {filtered.map(p => (
            <div key={p.id}>
              {editingId === p.id ? (
                <ProfileInlineForm
                  initial={{ name: p.name, description: p.description, color: p.color, avatar_url: p.avatar_url }}
                  onSave={data => updateMutation.mutate({ id: p.id, data })}
                  onCancel={() => setEditingId(null)}
                  loading={updateMutation.isPending}
                />
              ) : (
                <SidebarItem
                  active={selected === p.id}
                  onClick={() => onSelect(p.id)}
                  label={p.name}
                  count={p.account_count}
                  color={p.color}
                  avatar={p.avatar_url}
                  hidden={!!p.is_hidden}
                  onEdit={() => { setEditingId(p.id); setShowCreate(false); }}
                  onDelete={() => setDeletingProfile(p)}
                  onHide={() => onToggleHidden(p.id)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Delete dialog */}
      {deletingProfile && (
        <ProfileDeleteDialog
          profile={deletingProfile}
          onConfirm={deleteAccounts => deleteMutation.mutate({ id: deletingProfile.id, deleteAccounts })}
          onCancel={() => setDeletingProfile(null)}
        />
      )}
    </aside>
  );
}

// ── Inline profile form (compact, fits in 224px sidebar) ─────────────────────

function ProfileInlineForm({
  initial, onSave, onCancel, loading,
}: {
  initial: ProfileInput;
  onSave: (data: ProfileInput) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [name, setName] = useState(initial.name);
  const [color, setColor] = useState(initial.color);

  return (
    <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 mb-1 flex flex-col gap-2">
      <input
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder="Название"
        autoFocus
        className="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        onKeyDown={e => { if (e.key === "Enter" && name.trim()) onSave({ ...initial, name, color }); if (e.key === "Escape") onCancel(); }}
      />
      {/* Color swatches */}
      <div className="flex gap-1 flex-wrap">
        {PRESET_COLORS.map(c => (
          <button
            key={c}
            type="button"
            onClick={() => setColor(c)}
            className={`w-4 h-4 rounded-full border transition-transform ${color === c ? "border-white scale-125" : "border-transparent hover:scale-110"}`}
            style={{ background: c }}
          />
        ))}
      </div>
      <div className="flex gap-1.5">
        <button
          onClick={() => onSave({ ...initial, name, color })}
          disabled={!name.trim() || loading}
          className="flex-1 bg-white text-black text-xs font-semibold py-1 rounded disabled:opacity-40 hover:bg-zinc-100 transition-colors"
        >
          {loading ? "…" : "Сохранить"}
        </button>
        <button
          onClick={onCancel}
          className="text-zinc-500 hover:text-zinc-300 text-xs px-2 py-1 rounded transition-colors"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

// ── Delete confirmation dialog ────────────────────────────────────────────────

function ProfileDeleteDialog({
  profile, onConfirm, onCancel,
}: {
  profile: Profile;
  onConfirm: (deleteAccounts: boolean) => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-sm space-y-4">
        <h3 className="font-semibold text-white text-base">Удалить «{profile.name}»?</h3>
        {profile.account_count > 0 && (
          <p className="text-zinc-400 text-sm">
            Привязано <strong className="text-white">{profile.account_count}</strong>{" "}
            {profile.account_count === 1 ? "аккаунт" : profile.account_count < 5 ? "аккаунта" : "аккаунтов"}.
            Что с ними сделать?
          </p>
        )}
        <div className="flex flex-col gap-2">
          {profile.account_count === 0 ? (
            <button
              onClick={() => onConfirm(false)}
              className="w-full bg-red-900/60 hover:bg-red-900 border border-red-800 text-red-300 py-2 rounded-xl text-sm font-medium transition-colors"
            >
              Удалить профиль
            </button>
          ) : (
            <>
              <button
                onClick={() => onConfirm(false)}
                className="w-full bg-zinc-800 hover:bg-zinc-700 text-white py-2 rounded-xl text-sm font-medium transition-colors"
              >
                Оставить аккаунты без профиля
              </button>
              <button
                onClick={() => onConfirm(true)}
                className="w-full bg-red-900/60 hover:bg-red-900 border border-red-800 text-red-300 py-2 rounded-xl text-sm font-medium transition-colors"
              >
                Удалить профиль и все аккаунты
              </button>
            </>
          )}
          <button
            onClick={onCancel}
            className="w-full text-zinc-500 hover:text-zinc-300 py-1.5 text-sm transition-colors"
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Sidebar item ──────────────────────────────────────────────────────────────

function SidebarItem({ active, onClick, label, count, color, avatar, muted, onEdit, onDelete, onHide, hidden }: {
  active: boolean; onClick: () => void; label: string;
  count: number | null; color: string | null; avatar?: string; muted?: boolean;
  onEdit?: () => void; onDelete?: () => void;
  onHide?: () => void; hidden?: boolean;
}) {
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors text-sm ${
          active ? "bg-zinc-800 text-white" : muted ? "text-zinc-600 hover:text-zinc-400 hover:bg-zinc-900" : "text-zinc-400 hover:text-white hover:bg-zinc-900"
        }`}
      >
        {color ? (
          <div className="w-5 h-5 rounded-full shrink-0 flex items-center justify-center text-white text-xs font-bold overflow-hidden" style={{ background: color }}>
            {avatar ? (
              <img src={avatar} alt="" className="w-full h-full object-cover"
                onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
            ) : label.charAt(0).toUpperCase()}
          </div>
        ) : (
          <div className="w-5 h-5 rounded-full shrink-0 bg-zinc-800 border border-zinc-700" />
        )}
        <span className="truncate flex-1">{label}</span>
        {/* Count — hidden when action buttons are visible */}
        {count !== null && (
          <span className={`text-xs text-zinc-600 shrink-0 ${(onEdit || onDelete || onHide) ? "group-hover:hidden" : ""}`}>{count}</span>
        )}
        {/* Action buttons — only on profiles (when callbacks provided) */}
        {(onEdit || onDelete || onHide) && (
          <span className="hidden group-hover:flex items-center gap-0.5 shrink-0">
            {onHide && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); onHide(); }}
                className={`p-0.5 rounded border transition-colors ${
                  hidden
                    ? "border-emerald-300/60 bg-emerald-300/20 text-emerald-100 hover:bg-emerald-300/30"
                    : "border-red-400/40 bg-red-500/10 text-red-300 hover:bg-red-500/20"
                }`}
                title={hidden ? "Показать профиль" : "Скрыть профиль"}
              >
                <EyeIcon crossed={!hidden} className="w-3.5 h-3.5" />
              </span>
            )}
            {onEdit && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); onEdit(); }}
                className="p-0.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700 transition-colors"
                title="Изменить"
              >
                {/* Pencil icon */}
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H7v-3a2 2 0 01.586-1.414z" />
                </svg>
              </span>
            )}
            {onDelete && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); onDelete(); }}
                className="p-0.5 rounded text-zinc-500 hover:text-red-400 hover:bg-zinc-700 transition-colors"
                title="Удалить"
              >
                {/* X icon */}
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </span>
            )}
          </span>
        )}
      </button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

/** Если GET /schedule/ упал — модалка всё равно открывается с этими значениями. */
const DEFAULT_REFRESH_SCHEDULE: RefreshSchedule = {
  enabled: false,
  mode: "interval",
  interval_hours: 6,
  skip_recent_hours: 0,
  auto_refresh_csv_report: false,
  include_hidden_platform_accounts: false,
  include_hidden_profile_accounts: false,
  times: [],
};

const LS_MAIN_FILTER_PLATFORM = "accounts-main-filter-platform";
const LS_MAIN_FILTER_PROFILE = "accounts-main-filter-profile";
const LS_MAIN_FILTER_AVAILABILITY = "accounts-main-filter-availability";
const LS_MAIN_FILTER_SEARCH = "accounts-main-filter-search";

function readMainProfileFilterFromStorage(): number | "none" | null {
  try {
    const raw = window.localStorage.getItem(LS_MAIN_FILTER_PROFILE);
    if (!raw || raw === "all") return null;
    if (raw === "none") return "none";
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

export default function Accounts({ initialTab = "accounts" }: { initialTab?: Tab }) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>(initialTab);

  // Accounts state
  const [selectedPlatform, setSelectedPlatform] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LS_MAIN_FILTER_PLATFORM) || "";
    } catch {
      return "";
    }
  });
  const [showHiddenAccounts, setShowHiddenAccounts] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState<number | "none" | null>(() => readMainProfileFilterFromStorage());
  const [availabilityMainFilter, setAvailabilityMainFilter] = useState<AvailabilityMainFilter>(() => {
    try {
      const raw = window.localStorage.getItem(LS_MAIN_FILTER_AVAILABILITY);
      return raw === "available" || raw === "unavailable" ? raw : "all";
    } catch {
      return "all";
    }
  });
  const [searchRaw, setSearchRaw] = useState(() => {
    try {
      return window.localStorage.getItem(LS_MAIN_FILTER_SEARCH) || "";
    } catch {
      return "";
    }
  });
  const search = useDeferredValue(searchRaw);
  const [showAdd, setShowAdd] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState<Account | null>(null);
  const [newUsername, setNewUsername] = useState("");
  // Track account IDs currently being auto-refreshed after creation
  const [autoRefreshingIds, setAutoRefreshingIds] = useState<Set<number>>(new Set());
  const [newPlatform, setNewPlatform] = useState("tiktok");
  const [newProfileId, setNewProfileId] = useState<string>("");

  // Modal state
  const [showSchedule, setShowSchedule] = useState(false);
  const [showBulkAdd, setShowBulkAdd] = useState(false);
  const [showRefreshModal, setShowRefreshModal] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("view_count");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

  const qc = useQueryClient();
  const [showAutoRefreshWidget, setShowAutoRefreshWidget] = useState<boolean>(() => {
    try {
      const raw = window.localStorage.getItem("show-auto-refresh-widget");
      return raw == null ? true : raw === "1";
    } catch {
      return true;
    }
  });

  const {
    data: schedule,
    isError: scheduleQueryFailed,
    isFetching: scheduleFetching,
    refetch: refetchSchedule,
  } = useQuery<RefreshSchedule>({
    queryKey: ["schedule"],
    queryFn: getSchedule,
    staleTime: 30_000,
    retry: 3,
    retryDelay: (n) => Math.min(1500 * n, 8000),
  });
  const scheduleEffective = schedule ?? DEFAULT_REFRESH_SCHEDULE;

  useEffect(() => {
    try {
      window.localStorage.setItem("show-auto-refresh-widget", showAutoRefreshWidget ? "1" : "0");
    } catch {
      // ignore storage issues
    }
  }, [showAutoRefreshWidget]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_MAIN_FILTER_PLATFORM, selectedPlatform || "");
    } catch {
      // ignore storage issues
    }
  }, [selectedPlatform]);

  useEffect(() => {
    try {
      const encoded = selectedProfile === null ? "all" : selectedProfile === "none" ? "none" : String(selectedProfile);
      window.localStorage.setItem(LS_MAIN_FILTER_PROFILE, encoded);
    } catch {
      // ignore storage issues
    }
  }, [selectedProfile]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_MAIN_FILTER_AVAILABILITY, availabilityMainFilter);
    } catch {
      // ignore storage issues
    }
  }, [availabilityMainFilter]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_MAIN_FILTER_SEARCH, searchRaw);
    } catch {
      // ignore storage issues
    }
  }, [searchRaw]);

  const { data: autoRefreshStatus } = useQuery<AutoRefreshStatus>({
    queryKey: ["auto-refresh-status"],
    queryFn: getAutoRefreshStatus,
    staleTime: 1500,
    refetchInterval: (q) => {
      const s = q.state.data as AutoRefreshStatus | undefined;
      if (s?.is_running) return 2000;
      return scheduleEffective.enabled ? 7000 : 15000;
    },
    refetchOnWindowFocus: true,
  });

  const runAutoRefreshNowMutation = useMutation({
    mutationFn: runAutoRefreshNow,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auto-refresh-status"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
  const stopAutoRefreshMutation = useMutation({
    mutationFn: stopAutoRefresh,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auto-refresh-status"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const saveVisibilityMutation = useMutation({
    mutationFn: setGlobalVisibility,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["global-visibility"] });
      qc.invalidateQueries({ queryKey: ["platforms"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["profiles"] });
    },
  });

  const { data: platforms = [] } = useQuery<Platform[]>({
    queryKey: ["platforms"],
    queryFn: getPlatforms,
    staleTime: Infinity,
  });

  const { data: visibility } = useQuery({
    queryKey: ["global-visibility"],
    queryFn: getGlobalVisibility,
    staleTime: 15_000,
  });

  const { data: profiles = [] } = useQuery<Profile[]>({
    queryKey: ["profiles", { includeHidden: showHiddenAccounts }],
    queryFn: () => getProfiles({ includeHidden: showHiddenAccounts }),
    staleTime: 30_000,
  });

  const hiddenPlatformSet = useMemo(
    () => new Set((visibility?.hidden_platforms ?? []).map((v) => v.toLowerCase())),
    [visibility?.hidden_platforms],
  );

  const visiblePlatforms = useMemo(
    () => (showHiddenAccounts ? platforms : platforms.filter((p) => !hiddenPlatformSet.has(p.value))),
    [platforms, showHiddenAccounts, hiddenPlatformSet],
  );

  const visibleProfiles = useMemo(
    () => (showHiddenAccounts ? profiles : profiles.filter((p) => !p.is_hidden)),
    [profiles, showHiddenAccounts],
  );

  useEffect(() => {
    if (!showHiddenAccounts && selectedProfile !== null && selectedProfile !== "none") {
      const existsInVisible = visibleProfiles.some((p) => p.id === selectedProfile);
      if (!existsInVisible) setSelectedProfile(null);
    }
  }, [showHiddenAccounts, selectedProfile, visibleProfiles]);

  const filter = {
    platform: selectedPlatform || undefined,
    profile_id: selectedProfile ?? undefined,
    search: search || undefined,
    include_hidden: showHiddenAccounts || undefined,
  };

  const {
    data: accounts = [], isLoading, isError: accountsLoadError, error: accountsLoadErr, refetch: refetchAccounts,
  } = useQuery<Account[]>({
    queryKey: ["accounts", filter],
    queryFn: () => getAccounts(filter),
  });

  const { data: allAccounts = [] } = useQuery<Account[]>({
    queryKey: ["accounts", "all-for-refresh-modal"],
    queryFn: () => getAccounts({
      include_hidden: true,
      include_hidden_platforms: true,
      include_hidden_profiles: true,
    }),
    staleTime: 15_000,
  });

  const filteredAccounts = useMemo(() => {
    if (availabilityMainFilter === "available") {
      return accounts.filter((a) => !a.profile_unavailable);
    }
    if (availabilityMainFilter === "unavailable") {
      return accounts.filter((a) => !!a.profile_unavailable);
    }
    return accounts;
  }, [accounts, availabilityMainFilter]);

  const sortedAccounts = useMemo(() => {
    const arr = [...filteredAccounts];
    arr.sort((a, b) => {
      if (sortKey === "updated_at") {
        const diff = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
        return sortOrder === "asc" ? diff : -diff;
      }
      const diff = (a[sortKey] ?? 0) - (b[sortKey] ?? 0);
      return sortOrder === "asc" ? diff : -diff;
    });
    return arr;
  }, [filteredAccounts, sortKey, sortOrder]);

  const changeSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortOrder("asc");
  };

  const resetMainFilters = () => {
    setSelectedPlatform("");
    setSelectedProfile(null);
    setAvailabilityMainFilter("all");
    setSearchRaw("");
  };

  const togglePlatformHidden = async (platformValue: string) => {
    const current = new Set(visibility?.hidden_platforms ?? []);
    if (current.has(platformValue)) current.delete(platformValue);
    else current.add(platformValue);
    await saveVisibilityMutation.mutateAsync({ hidden_platforms: Array.from(current) });
  };

  const toggleProfileHidden = async (profileId: number) => {
    const hidden = new Set(visibility?.hidden_profile_ids ?? []);
    if (hidden.has(profileId)) hidden.delete(profileId);
    else hidden.add(profileId);
    await saveVisibilityMutation.mutateAsync({ hidden_profile_ids: Array.from(hidden) });
  };

  // Compute header stats from the currently displayed accounts (respects filters, always in sync)
  const computedSummary = useMemo(() => {
    if (!filteredAccounts.length) return null;
    let follower_count = 0, like_count = 0, view_count = 0, post_count = 0;
    let follower_delta: number | null = null;
    let like_delta: number | null = null;
    let view_delta: number | null = null;
    let post_delta: number | null = null;
    for (const acc of filteredAccounts) {
      follower_count += acc.follower_count;
      like_count     += acc.like_count;
      view_count     += acc.view_count;
      post_count     += acc.post_count;
      if (acc.follower_delta != null) follower_delta = (follower_delta ?? 0) + acc.follower_delta;
      if (acc.like_delta     != null) like_delta     = (like_delta     ?? 0) + acc.like_delta;
      if (acc.view_delta     != null) view_delta     = (view_delta     ?? 0) + acc.view_delta;
      if (acc.post_delta     != null) post_delta     = (post_delta     ?? 0) + acc.post_delta;
    }
    return { account_count: filteredAccounts.length, follower_count, like_count, view_count, post_count,
             follower_delta, like_delta, view_delta, post_delta };
  }, [filteredAccounts]);

  const addMutation = useMutation({
    mutationFn: () => createAccount({
      username: newUsername.trim().replace(/^@/, ""),
      platform: newPlatform,
      profile_id: newProfileId ? Number(newProfileId) : null,
    }),
    onSuccess: (newAccount) => {
      // Optimistic profile count — increment immediately, server confirms on next refetch
      if (newProfileId) {
        const pid = Number(newProfileId);
        qc.setQueryData<Profile[]>(["profiles"], old =>
          old ? old.map(p => p.id === pid ? { ...p, account_count: p.account_count + 1 } : p) : old
        );
      }
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["profiles"] });
      setShowAdd(false);
      setNewUsername("");
      setNewProfileId("");
      // Auto-refresh: show spinner on the new row
      setAutoRefreshingIds(prev => new Set(prev).add(newAccount.id));
      refreshAccount(newAccount.id)
        .then(() => qc.invalidateQueries({ queryKey: ["accounts"] }))
        .catch(() => {})
        .finally(() => {
          setAutoRefreshingIds(prev => { const s = new Set(prev); s.delete(newAccount.id); return s; });
        });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeletingAccount(null);
    },
  });

  const downloadRefreshCsv = (report: RefreshReportRow[]) => {
    const header = [
      "platform",
      "username",
      "status",
      "follower_count",
      "follower_delta",
      "like_count",
      "like_delta",
      "view_count",
      "view_delta",
      "post_count",
      "post_delta",
      "error",
    ];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [
      header.join(","),
      ...report.map((r) =>
        [
          r.platform,
          r.username,
          r.status,
          r.follower_count,
          r.follower_delta ?? "",
          r.like_count,
          r.like_delta ?? "",
          r.view_count,
          r.view_delta ?? "",
          r.post_count,
          r.post_delta ?? "",
          r.error ?? "",
        ].map(esc).join(",")
      ),
    ];
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url;
    a.download = `refresh-all-report-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  const refreshSelectionAbortRef = useRef<AbortController | null>(null);

  const [refreshProgress, setRefreshProgress] = useState<{
    done: number;
    total: number;
    busyHint?: string | null;
    activeLabel?: string | null;
  }>({
    done: 0,
    total: 0,
    busyHint: null,
    activeLabel: null,
  });
  const [lastRefreshReport, setLastRefreshReport] = useState<RefreshReportRow[] | null>(null);
  const [lastRefreshErrors, setLastRefreshErrors] = useState<string[]>([]);
  const [lastRefreshDurationSec, setLastRefreshDurationSec] = useState<number | null>(null);
  const [showRefreshErrorList, setShowRefreshErrorList] = useState(false);
  const [showRefreshBanner, setShowRefreshBanner] = useState(false);
  const refreshErrorListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showRefreshErrorList) return;
    const onDown = (e: MouseEvent) => {
      if (refreshErrorListRef.current && !refreshErrorListRef.current.contains(e.target as Node)) {
        setShowRefreshErrorList(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [showRefreshErrorList]);

  useEffect(() => {
    if (!lastRefreshReport) return;
    setShowRefreshBanner(true);
    const t = window.setTimeout(() => setShowRefreshBanner(false), 7000);
    return () => window.clearTimeout(t);
  }, [lastRefreshReport, lastRefreshDurationSec]);

  const runSelectedRefresh = async (accountIds: number[], downloadCsv: boolean): Promise<boolean> => {
    const refreshStarted = performance.now();
    const byId = new Map(allAccounts.map((a) => [a.id, a] as const));
    const rowsById = new Map<number, RefreshReportRow>();
    const errorsById = new Map<number, string>();
    const total = accountIds.filter((id) => byId.has(id)).length;
    setRefreshProgress({ done: 0, total, busyHint: null, activeLabel: null });
    setLastRefreshReport(null);
    setLastRefreshErrors([]);
    setLastRefreshDurationSec(null);
    setShowRefreshErrorList(false);

    const applyReportRow = (before: Account, after: Account) => {
      const changed = [
        after.follower_count !== before.follower_count,
        after.like_count !== before.like_count,
        after.view_count !== before.view_count,
        after.post_count !== before.post_count,
      ];
      const changedCount = changed.filter(Boolean).length;
      const status: RefreshStatusLabel =
        changedCount === changed.length ? "обновилось" :
        changedCount === 0 ? "нет обновлений" :
        "обновилось";
      rowsById.set(before.id, {
        id: after.id,
        platform: after.platform,
        username: after.username,
        status,
        follower_count: after.follower_count,
        follower_delta: after.follower_count - before.follower_count,
        like_count: after.like_count,
        like_delta: after.like_count - before.like_count,
        view_count: after.view_count,
        view_delta: after.view_count - before.view_count,
        post_count: after.post_count,
        post_delta: after.post_count - before.post_count,
      });
    };

    const refreshOne = async (id: number, signal: AbortSignal) => {
      const before = byId.get(id);
      if (!before) return;
      if (signal.aborted) return;
      setRefreshProgress((p) => ({
        ...p,
        activeLabel: `${before.platform_label} · @${before.username}`,
      }));
      let cancelled = false;
      try {
        const after = await refreshAccount(id, { signal });
        applyReportRow(before, after);
      } catch (e: unknown) {
        if (axios.isCancel(e) || (e as { code?: string })?.code === "ERR_CANCELED") {
          cancelled = true;
          throw e;
        }
        const errText =
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          (e as Error)?.message ||
          "Ошибка";
        errorsById.set(id, errText);
        rowsById.set(id, {
          id: before.id,
          platform: before.platform,
          username: before.username,
          status: "ошибка",
          follower_count: before.follower_count,
          follower_delta: null,
          like_count: before.like_count,
          like_delta: null,
          view_count: before.view_count,
          view_delta: null,
          post_count: before.post_count,
          post_delta: null,
          error: errText,
        });
      } finally {
        if (!cancelled) {
          setRefreshProgress((p) => ({ ...p, done: p.done + 1 }));
        }
      }
    };

    const validIds = accountIds.filter((id) => byId.has(id));
    const delayMinMs = 3_000;
    const delayMaxMs = 7_000;
    const byPlatform = new Map<string, number[]>();
    for (const id of validIds) {
      const p = byId.get(id)!.platform;
      const list = byPlatform.get(p) ?? [];
      list.push(id);
      byPlatform.set(p, list);
    }

    const ac = new AbortController();
    const signal = ac.signal;
    refreshSelectionAbortRef.current = ac;

    const cancelledRow = (before: Account, msg: string): RefreshReportRow => ({
      id: before.id,
      platform: before.platform,
      username: before.username,
      status: "ошибка",
      follower_count: before.follower_count,
      follower_delta: null,
      like_count: before.like_count,
      like_delta: null,
      view_count: before.view_count,
      view_delta: null,
      post_count: before.post_count,
      post_delta: null,
      error: msg,
    });

    try {
      await Promise.all(
        [...byPlatform.entries()].map(async ([platform, ids]) => {
        if (platform === "instagram" && ids.length > 1) {
          const chunkSize = 3;
          const chunks: number[][] = [];
          for (let i = 0; i < ids.length; i += chunkSize) {
            chunks.push(ids.slice(i, i + chunkSize));
          }
          for (let ci = 0; ci < chunks.length; ci++) {
            if (signal.aborted) break;
            const chunkIds = chunks[ci];
            setRefreshProgress((p) => ({
              ...p,
              activeLabel: `Instagram · пакет ${ci + 1}/${chunks.length}`,
              busyHint: `Обновляю ${chunkIds.length} акк. в пакете`,
            }));
            try {
              const bulk = await refreshAccountsBulk(chunkIds, { signal });
              const afterList = bulk.accounts ?? [];
              const bulkErrors = bulk.errors ?? [];
              const afterById = new Map(afterList.map((a) => [Number(a.id), a] as const));
              for (const id of chunkIds) {
                const before = byId.get(id);
                if (!before) continue;
                const after = afterById.get(Number(id));
                const err = bulkErrors.find((e) => Number(e.id) === Number(id));
                if (err) {
                  errorsById.set(id, err.detail);
                  rowsById.set(id, {
                    id: before.id,
                    platform: before.platform,
                    username: before.username,
                    status: "ошибка",
                    follower_count: before.follower_count,
                    follower_delta: null,
                    like_count: before.like_count,
                    like_delta: null,
                    view_count: before.view_count,
                    view_delta: null,
                    post_count: before.post_count,
                    post_delta: null,
                    error: err.detail,
                  });
                } else if (after) {
                  applyReportRow(before, after);
                } else {
                  const msg = "Нет ответа по аккаунту в bulk-refresh (проверьте логи сервера)";
                  errorsById.set(id, msg);
                  rowsById.set(id, {
                    id: before.id,
                    platform: before.platform,
                    username: before.username,
                    status: "ошибка",
                    follower_count: before.follower_count,
                    follower_delta: null,
                    like_count: before.like_count,
                    like_delta: null,
                    view_count: before.view_count,
                    view_delta: null,
                    post_count: before.post_count,
                    post_delta: null,
                    error: msg,
                  });
                }
                setRefreshProgress((p) => ({ ...p, done: p.done + 1 }));
              }
            } catch (e: unknown) {
              if (axios.isCancel(e) || (e as { code?: string })?.code === "ERR_CANCELED") {
                throw e;
              }
              // If bulk chunk failed, fallback to per-account requests for this chunk.
              for (const id of chunkIds) {
                if (signal.aborted) break;
                try {
                  await refreshOne(id, signal);
                } catch (inner: unknown) {
                  if (axios.isCancel(inner) || (inner as { code?: string })?.code === "ERR_CANCELED") {
                    break;
                  }
                }
              }
            }
          }
          setRefreshProgress((p) => ({ ...p, busyHint: null }));
          return;
        }
        for (const id of ids) {
          if (signal.aborted) break;
          try {
            await refreshOne(id, signal);
            const isLast = id === ids[ids.length - 1];
            if (!isLast && !signal.aborted) {
              const pauseMs = Math.floor(delayMinMs + Math.random() * (delayMaxMs - delayMinMs));
              setRefreshProgress((p) => ({
                ...p,
                busyHint: `Пауза перед следующим аккаунтом: ${Math.round(pauseMs / 1000)}с`,
              }));
              await sleep(pauseMs);
            }
          } catch (e: unknown) {
            if (axios.isCancel(e) || (e as { code?: string })?.code === "ERR_CANCELED") {
              break;
            }
            throw e;
          }
        }
      }),
      );
    } catch (e: unknown) {
      if (!axios.isCancel(e) && (e as { code?: string })?.code !== "ERR_CANCELED") {
        throw e;
      }
    } finally {
      refreshSelectionAbortRef.current = null;
      if (signal.aborted) {
        for (const id of validIds) {
          if (rowsById.has(id)) continue;
          const before = byId.get(id);
          if (!before) continue;
          const msg = "Отменено пользователем";
          errorsById.set(id, msg);
          rowsById.set(id, cancelledRow(before, msg));
        }
        setRefreshProgress({ done: total, total, busyHint: null, activeLabel: null });
      }
    }

    const report = accountIds
      .map((id) => rowsById.get(id))
      .filter((row): row is RefreshReportRow => row !== undefined);
    const errors = accountIds
      .map((id) => {
        const errText = errorsById.get(id);
        if (!errText) return null;
        const before = byId.get(id);
        return before ? `@${before.username} (${before.platform}): ${errText}` : errText;
      })
      .filter((s): s is string => s !== null);

    setLastRefreshDurationSec((performance.now() - refreshStarted) / 1000);
    setLastRefreshReport(report);
    setLastRefreshErrors(errors);
    if (downloadCsv) downloadRefreshCsv(report);
    qc.invalidateQueries({ queryKey: ["accounts"] });
    setRefreshProgress((p) => ({ ...p, activeLabel: null, busyHint: null }));
    return signal.aborted;
  };

  return (
    <div className="min-h-screen bg-black text-white">

      {/* ── Header ── */}
      <header className="sticky top-0 z-10 bg-black/90 backdrop-blur border-b border-zinc-800 px-4 py-3">
        <div className="max-w-[1400px] mx-auto flex items-center gap-3 sm:gap-4">
          <span className="text-white font-bold text-lg shrink-0">AccountsStats</span>

          {/* Compact stats — computed from currently displayed accounts */}
          {computedSummary && (
            <div className="hidden sm:flex items-center gap-5 ml-4 flex-1 overflow-x-auto">
              <div className="w-px h-6 bg-zinc-800 shrink-0" />
              <StatPill label="Подписчики" value={computedSummary.follower_count} delta={computedSummary.follower_delta} />
              <div className="w-px h-6 bg-zinc-800 shrink-0" />
              <StatPill label="Просмотры" value={computedSummary.view_count} delta={computedSummary.view_delta} />
              <div className="w-px h-6 bg-zinc-800 shrink-0" />
              <StatPill label="Лайки" value={computedSummary.like_count} delta={computedSummary.like_delta} />
              <div className="w-px h-6 bg-zinc-800 shrink-0" />
              <StatPill label="Публикации" value={computedSummary.post_count} delta={computedSummary.post_delta} />
              <span className="text-xs text-zinc-600 shrink-0 ml-1">{computedSummary.account_count} акк.</span>
            </div>
          )}

          <div className="hidden md:flex items-center gap-2 ml-auto shrink-0">
            <button
              onClick={() => setShowRefreshModal(true)}
              className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-500 px-3 py-1.5 rounded-xl transition-colors"
            >
              <RefreshIcon />
              Обновить всё
            </button>

            {/* Auto-refresh toggle + settings */}
            <div className="flex items-center border border-zinc-700 hover:border-zinc-500 rounded-xl overflow-hidden transition-colors">
              <button
                type="button"
                disabled={scheduleFetching && !schedule}
                onClick={() => {
                  void setSchedule({ enabled: !scheduleEffective.enabled })
                    .then(() => qc.invalidateQueries({ queryKey: ["schedule"] }))
                    .catch(() => qc.invalidateQueries({ queryKey: ["schedule"] }));
                }}
                className={`flex items-center gap-1.5 text-sm px-3 py-1.5 transition-colors disabled:opacity-40 ${
                  scheduleEffective.enabled ? "text-emerald-400 hover:text-emerald-300" : "text-zinc-400 hover:text-white"
                }`}
                title={scheduleEffective.enabled ? "Автообновление включено" : "Автообновление выключено"}
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${scheduleEffective.enabled ? "bg-emerald-400" : "bg-zinc-600"}`} />
                Автообновление
              </button>
              <button
                type="button"
                onClick={() => setShowSchedule(true)}
                className="border-l border-zinc-700 px-2 py-1.5 text-zinc-500 hover:text-white hover:bg-zinc-800 transition-colors"
                title="Настроить расписание"
              >
                {/* Pencil icon */}
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H7v-3a2 2 0 01.586-1.414z" />
                </svg>
              </button>
            </div>

            {/* Bulk add */}
            <button
              onClick={() => setShowBulkAdd(true)}
              className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-500 px-3 py-1.5 rounded-xl transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              Добавить список
            </button>

            {/* Single add */}
            <button
              onClick={() => setShowAdd(v => !v)}
              className="bg-white text-black text-sm font-semibold px-4 py-1.5 rounded-xl hover:bg-zinc-100 transition-colors"
            >
              + Добавить
            </button>

            {/* Settings */}
            <button
              onClick={() => navigate("/settings")}
              title="Настройки авторизации"
              className="w-8 h-8 flex items-center justify-center rounded-xl border border-zinc-700 hover:border-zinc-500 text-zinc-400 hover:text-white transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>
          </div>
        </div>
        {computedSummary && (
          <div className="sm:hidden max-w-[1400px] mx-auto mt-2 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 py-1.5">
              <span className="text-[10px] text-zinc-500">Подписчики</span>
              <div className="flex items-baseline gap-1.5">
                <div className="text-sm font-semibold">{fmt(computedSummary.follower_count)}</div>
                {computedSummary.follower_delta != null && computedSummary.follower_delta !== 0 && (
                  <span className={`text-[10px] ${computedSummary.follower_delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtDelta(computedSummary.follower_delta)}
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 py-1.5">
              <span className="text-[10px] text-zinc-500">Просмотры</span>
              <div className="flex items-baseline gap-1.5">
                <div className="text-sm font-semibold">{fmt(computedSummary.view_count)}</div>
                {computedSummary.view_delta != null && computedSummary.view_delta !== 0 && (
                  <span className={`text-[10px] ${computedSummary.view_delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtDelta(computedSummary.view_delta)}
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 py-1.5">
              <span className="text-[10px] text-zinc-500">Лайки</span>
              <div className="flex items-baseline gap-1.5">
                <div className="text-sm font-semibold">{fmt(computedSummary.like_count)}</div>
                {computedSummary.like_delta != null && computedSummary.like_delta !== 0 && (
                  <span className={`text-[10px] ${computedSummary.like_delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtDelta(computedSummary.like_delta)}
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 py-1.5">
              <span className="text-[10px] text-zinc-500">Публикации</span>
              <div className="flex items-baseline gap-1.5">
                <div className="text-sm font-semibold">{fmt(computedSummary.post_count)}</div>
                {computedSummary.post_delta != null && computedSummary.post_delta !== 0 && (
                  <span className={`text-[10px] ${computedSummary.post_delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtDelta(computedSummary.post_delta)}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {showAutoRefreshWidget && autoRefreshStatus?.is_running && (
          <div className="max-w-[1400px] mx-auto mt-2">
            <AutoRefreshProgressCard
              status={autoRefreshStatus}
              enabled={!!scheduleEffective.enabled}
              onOpenSettings={() => setShowSchedule(true)}
            />
          </div>
        )}

        {showRefreshBanner && lastRefreshReport && (
          <div ref={refreshErrorListRef} className="max-w-[1400px] mx-auto mt-1 text-xs text-zinc-400 relative">
            Обновлено: {lastRefreshReport.filter((r) => r.status !== "ошибка").length}
            {lastRefreshErrors.length > 0 && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => setShowRefreshErrorList((o) => !o)}
                  className="text-red-400 hover:text-red-300 hover:underline cursor-pointer align-baseline"
                  aria-expanded={showRefreshErrorList}
                >
                  · {refreshErrorsCountRu(lastRefreshErrors.length)}
                </button>
                {showRefreshErrorList && (
                  <div
                    className="absolute left-0 top-full z-50 mt-1 min-w-[260px] max-w-md rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-left shadow-xl"
                    role="dialog"
                    aria-label="Аккаунты с ошибкой обновления"
                  >
                    <div className="font-semibold text-white mb-2 text-sm">Ошибки обновления</div>
                    <ul className="space-y-2">
                      {lastRefreshReport.filter((r) => r.status === "ошибка").length > 0 ? (
                        lastRefreshReport
                          .filter((r) => r.status === "ошибка")
                          .map((r) => (
                            <li key={r.id} className="border-b border-zinc-800 pb-2 last:border-0 last:pb-0">
                              <div className="flex items-center gap-2 text-white text-sm">
                                <PlatformIcon platform={r.platform} className="w-3.5 h-3.5 shrink-0" />
                                <span className="font-medium">{displayHandle(r.platform, r.username)}</span>
                              </div>
                              {r.error && (
                                <p className="mt-1 text-zinc-500 break-words leading-snug">{r.error}</p>
                              )}
                            </li>
                          ))
                      ) : (
                        lastRefreshErrors.map((line, i) => (
                          <li key={i} className="text-zinc-300 text-sm break-words">
                            {line}
                          </li>
                        ))
                      )}
                    </ul>
                  </div>
                )}
              </>
            )}
            {lastRefreshDurationSec != null && (
              <span className="text-zinc-500"> · {formatRefreshTotalDurationRu(lastRefreshDurationSec)}</span>
            )}
          </div>
        )}
      </header>

      <div className="max-w-[1400px] mx-auto px-4 py-6">

        {/* ── Tab switcher ── */}
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 w-full sm:w-fit mb-6">
          <TabBtn active={tab === "accounts"}   onClick={() => setTab("accounts")}>Аккаунты</TabBtn>
          <TabBtn active={tab === "analytics"}  onClick={() => setTab("analytics")}>Аналитика</TabBtn>
        </div>

        {tab === "accounts" && (
          <div className="md:hidden mb-4 grid grid-cols-5 gap-2">
            <button type="button" onClick={() => setShowRefreshModal(true)} className="h-9 rounded-xl border border-zinc-700 inline-flex items-center justify-center text-zinc-200 bg-zinc-900/60" title="Обновить всё">
              <RefreshIcon />
            </button>
            <button
              type="button"
              onClick={() => setShowSchedule(true)}
              className={`h-9 rounded-xl border inline-flex items-center justify-center bg-zinc-900/60 ${
                scheduleEffective.enabled ? "border-emerald-700/80 text-emerald-400" : "border-zinc-700 text-zinc-200"
              }`}
              title="Расписание автообновления"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button type="button" onClick={() => setShowBulkAdd(true)} className="h-9 rounded-xl border border-zinc-700 inline-flex items-center justify-center text-zinc-200 bg-zinc-900/60">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
            </button>
            <button type="button" onClick={() => setShowAdd(v => !v)} className="h-9 rounded-xl border border-zinc-700 inline-flex items-center justify-center text-zinc-200 bg-zinc-900/60">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" /></svg>
            </button>
            <button type="button" onClick={() => navigate("/settings")} className="h-9 rounded-xl border border-zinc-700 inline-flex items-center justify-center text-zinc-200 bg-zinc-900/60">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
            </button>
          </div>
        )}

        {/* ── Accounts tab ── */}
        {tab === "accounts" && (
          <div className="flex flex-col lg:flex-row gap-4 lg:gap-6">

            {/* Sidebar */}
            <div className="hidden lg:block">
              <ProfileSidebar
                profiles={visibleProfiles}
                selected={selectedProfile}
                onSelect={setSelectedProfile}
                onToggleHidden={toggleProfileHidden}
              />
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <details className="lg:hidden mb-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
                <summary className="text-sm text-zinc-200 cursor-pointer">Фильтр профиля</summary>
                <div className="mt-2">
                  <select
                    value={selectedProfile === null ? "" : selectedProfile === "none" ? "none" : String(selectedProfile)}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (!v) setSelectedProfile(null);
                      else if (v === "none") setSelectedProfile("none");
                      else setSelectedProfile(Number(v));
                    }}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                  >
                    <option value="">Все профили</option>
                    <option value="none">Без профиля</option>
                    {visibleProfiles.map((p) => (
                      <option key={p.id} value={String(p.id)}>{p.name}</option>
                    ))}
                  </select>
                </div>
              </details>

              {/* Search + platform filter */}
              <div className="flex flex-wrap gap-2 mb-5 items-center">
                <div className="relative flex-1 min-w-0 basis-full sm:basis-auto">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
                  </svg>
                  <input
                    value={searchRaw}
                    onChange={e => setSearchRaw(e.target.value)}
                    placeholder="Поиск аккаунтов..."
                    className="w-full bg-zinc-900 border border-zinc-800 rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-600"
                  />
                </div>
                <div className="hidden sm:flex gap-1 flex-wrap">
                  <FilterBtn active={!selectedPlatform} onClick={() => setSelectedPlatform("")}>Все</FilterBtn>
                  {visiblePlatforms.map((p) => (
                    <PlatformFilterChip
                      key={p.value}
                      active={selectedPlatform === p.value}
                      platform={p.value}
                      label={p.label}
                      hidden={hiddenPlatformSet.has(p.value)}
                      onClick={() => setSelectedPlatform(p.value)}
                      onHide={() => {
                        void togglePlatformHidden(p.value);
                      }}
                    />
                  ))}
                  <button
                    type="button"
                    onClick={() => setShowHiddenAccounts((v) => !v)}
                    className={`h-8 px-2.5 rounded-lg border inline-flex items-center justify-center transition-colors ${
                      showHiddenAccounts
                        ? "bg-white border-white text-black"
                        : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
                    }`}
                    title={showHiddenAccounts ? "Скрыть скрытые аккаунты" : "Показать все аккаунты (включая скрытые)"}
                  >
                    <EyeIcon crossed={!showHiddenAccounts} className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex sm:hidden gap-1 flex-nowrap overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                  <button
                    type="button"
                    onClick={() => setSelectedPlatform("")}
                    title="Все платформы"
                    className={`h-8 px-2 rounded-lg border text-xs ${!selectedPlatform ? "bg-white text-black border-white" : "bg-zinc-900 border-zinc-800 text-zinc-400"}`}
                  >
                    Все
                  </button>
                  {visiblePlatforms.map((p) => (
                    <PlatformIconFilterBtn
                      key={p.value}
                      active={selectedPlatform === p.value}
                      onClick={() => setSelectedPlatform(p.value)}
                      platform={p.value}
                      label={p.label}
                      onToggleHidden={() => {
                        void togglePlatformHidden(p.value);
                      }}
                      hidden={hiddenPlatformSet.has(p.value)}
                    />
                  ))}
                  <button
                    type="button"
                    onClick={() => setShowHiddenAccounts((v) => !v)}
                    title={showHiddenAccounts ? "Скрыть скрытые" : "Показать все"}
                    className={`h-8 w-8 rounded-lg border inline-flex items-center justify-center ${
                      showHiddenAccounts ? "bg-white text-black border-white" : "bg-zinc-900 border-zinc-800 text-zinc-400"
                    }`}
                  >
                    <EyeIcon crossed={!showHiddenAccounts} className="w-4 h-4" />
                  </button>
                </div>
                <div className="w-full flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={resetMainFilters}
                    className="h-8 px-2 sm:px-2.5 rounded-lg text-xs border border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors whitespace-nowrap inline-flex items-center gap-1"
                    title="Сбросить фильтры платформ, профилей, статуса и поиска"
                  >
                    <span aria-hidden>↺</span>
                    <span className="sm:hidden">Сбросить</span>
                    <span className="hidden sm:inline">Сбросить фильтры</span>
                  </button>
                  <FilterBtn
                    active={availabilityMainFilter === "all"}
                    onClick={() => setAvailabilityMainFilter("all")}
                  >
                    Все статусы
                  </FilterBtn>
                  <FilterBtn
                    active={availabilityMainFilter === "available"}
                    onClick={() => setAvailabilityMainFilter("available")}
                  >
                    Доступные
                  </FilterBtn>
                  <FilterBtn
                    active={availabilityMainFilter === "unavailable"}
                    onClick={() => setAvailabilityMainFilter("unavailable")}
                  >
                    Недоступные
                  </FilterBtn>
                </div>
              </div>

              <div className="mb-4 grid grid-cols-2 sm:grid-cols-4 gap-1.5 md:hidden">
                <button
                  type="button"
                  onClick={() => changeSort("follower_count")}
                  className={`px-2 py-1.5 rounded-lg text-[11px] border ${sortKey === "follower_count" ? "bg-white text-black border-white" : "border-zinc-800 text-zinc-400"}`}
                >
                  Подп. {sortKey === "follower_count" ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}
                </button>
                <button
                  type="button"
                  onClick={() => changeSort("view_count")}
                  className={`px-2 py-1.5 rounded-lg text-[11px] border ${sortKey === "view_count" ? "bg-white text-black border-white" : "border-zinc-800 text-zinc-400"}`}
                >
                  Просм. {sortKey === "view_count" ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}
                </button>
                <button
                  type="button"
                  onClick={() => changeSort("like_count")}
                  className={`px-2 py-1.5 rounded-lg text-[11px] border ${sortKey === "like_count" ? "bg-white text-black border-white" : "border-zinc-800 text-zinc-400"}`}
                >
                  Лайки {sortKey === "like_count" ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}
                </button>
                <button
                  type="button"
                  onClick={() => changeSort("post_count")}
                  className={`px-2 py-1.5 rounded-lg text-[11px] border ${sortKey === "post_count" ? "bg-white text-black border-white" : "border-zinc-800 text-zinc-400"}`}
                >
                  Публ. {sortKey === "post_count" ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}
                </button>
              </div>

              {/* Add form */}
              {showAdd && (
                <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-5 mb-5">
                  <h3 className="font-semibold mb-4 text-sm">Добавить аккаунт</h3>
                  <div className="flex gap-3 flex-wrap items-end">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-zinc-500">Платформа</label>
                      <select value={newPlatform} onChange={e => setNewPlatform(e.target.value)}
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500">
                        {visiblePlatforms.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1 flex-1 min-w-36">
                      <label className="text-xs text-zinc-500">Username</label>
                      <input
                        value={newUsername}
                        onChange={e => setNewUsername(e.target.value)}
                        placeholder={newPlatform === "rumble" ? "channel_name" : "@username"}
                        autoFocus
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                        onKeyDown={e => e.key === "Enter" && newUsername.trim() && addMutation.mutate()}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-zinc-500">Профиль</label>
                      <select value={newProfileId} onChange={e => setNewProfileId(e.target.value)}
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500">
                        <option value="">Без профиля</option>
                        {visibleProfiles.map(p => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
                      </select>
                    </div>
                    <button
                      onClick={() => addMutation.mutate()}
                      disabled={!newUsername.trim() || addMutation.isPending}
                      className="bg-white text-black text-sm font-semibold px-5 py-2 rounded-lg disabled:opacity-40 hover:bg-zinc-100 transition-colors"
                    >
                      {addMutation.isPending ? "Добавляю…" : "Добавить"}
                    </button>
                    <button onClick={() => setShowAdd(false)} className="text-zinc-500 hover:text-zinc-300 text-sm px-3 py-2">
                      Отмена
                    </button>
                  </div>
                  {addMutation.isError && (
                    <p className="text-red-400 text-xs mt-2">
                      {(addMutation.error as any)?.response?.data?.detail || "Ошибка. Возможно аккаунт уже добавлен."}
                    </p>
                  )}
                </div>
              )}

              {/* Account table */}
              {accountsLoadError ? (
                <div className="rounded-xl border border-red-900/70 bg-red-950/35 px-4 py-4 text-sm text-red-100">
                  <p className="font-medium mb-2">Не удалось загрузить аккаунты с сервера</p>
                  <p className="text-red-200/85 mb-3 text-xs sm:text-sm leading-relaxed space-y-1">
                    {axios.isAxiosError(accountsLoadErr) && accountsLoadErr.response?.status === 500
                      ? "Ответ API: HTTP 500. Смотри лог Django при старте — строка DB engine=…, host и имя базы должны быть от PostgreSQL. Проверь DATABASE_URL или DB_* в .env, после деплоев — migrate. Проверка БД: GET /healthz/ready/ (503 — база не отвечает)."
                      : axios.isAxiosError(accountsLoadErr) && accountsLoadErr.response?.status
                        ? `Ответ API: HTTP ${accountsLoadErr.response.status}. Если это не сеть — смотри логи бэкенда и схему БД (migrate).`
                        : axios.isAxiosError(accountsLoadErr)
                          ? "Сеть недоступна или бэкенд не запущен (например, нет процесса `runserver`)."
                          : "Неизвестная ошибка загрузки."}
                  </p>
                  <button
                    type="button"
                    onClick={() => void refetchAccounts()}
                    className="bg-red-950 border border-red-800 rounded-lg px-4 py-2 text-white hover:bg-red-900 transition-colors text-xs font-semibold"
                  >
                    Повторить запрос
                  </button>
                </div>
              ) : isLoading ? (
                <div className="flex justify-center py-20">
                  <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
                </div>
              ) : sortedAccounts.length === 0 ? (
                <div className="text-center py-20 text-zinc-600">
                  <p className="text-lg mb-2">Нет аккаунтов</p>
                  <p className="text-sm">{searchRaw ? "Попробуй изменить запрос" : "Нажми «+ Добавить» чтобы начать"}</p>
                </div>
              ) : (
                <>
                <div className="space-y-2 md:hidden">
                  {sortedAccounts.map(acc => (
                    <MobileAccountCard
                      key={acc.id}
                      account={acc}
                      onDelete={() => setDeletingAccount(acc)}
                      onRefresh={() => qc.invalidateQueries({ queryKey: ["accounts"] })}
                      isAutoRefreshing={autoRefreshingIds.has(acc.id)}
                    />
                  ))}
                </div>
                <div className="hidden md:block overflow-x-auto rounded-xl border border-zinc-800">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-zinc-800 bg-zinc-900/60">
                        <Th>Аккаунт</Th>
                        <Th>Платформа</Th>
                        <Th>Профиль</Th>
                        <SortableTh align="right" active={sortKey === "follower_count"} order={sortOrder} onClick={() => changeSort("follower_count")}>Подписчики</SortableTh>
                        <SortableTh align="right" active={sortKey === "view_count"} order={sortOrder} onClick={() => changeSort("view_count")}>Просмотры</SortableTh>
                        <SortableTh align="right" active={sortKey === "like_count"} order={sortOrder} onClick={() => changeSort("like_count")}>Лайки</SortableTh>
                        <SortableTh align="right" active={sortKey === "post_count"} order={sortOrder} onClick={() => changeSort("post_count")}>Публикации</SortableTh>
                        <SortableTh active={sortKey === "updated_at"} order={sortOrder} onClick={() => changeSort("updated_at")}>Обновлён</SortableTh>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedAccounts.map(acc => (
                        <AccountRow
                          key={acc.id}
                          account={acc}
                          onDelete={() => setDeletingAccount(acc)}
                          onRefresh={() => qc.invalidateQueries({ queryKey: ["accounts"] })}
                          isAutoRefreshing={autoRefreshingIds.has(acc.id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* ── Analytics tab ── */}
        {tab === "analytics" && <Analytics />}

      </div>

      {/* ── Modals ── */}
      {showSchedule && (
        <ScheduleModal
          initial={scheduleEffective}
          scheduleLoadFailed={scheduleQueryFailed}
          onRetryScheduleLoad={() => void refetchSchedule()}
          autoStatus={autoRefreshStatus}
          showAutoProgressWidget={showAutoRefreshWidget}
          onToggleAutoProgressWidget={setShowAutoRefreshWidget}
          onRunNow={() => runAutoRefreshNowMutation.mutateAsync()}
          runNowPending={runAutoRefreshNowMutation.isPending}
          onStopNow={() => stopAutoRefreshMutation.mutateAsync()}
          stopNowPending={stopAutoRefreshMutation.isPending}
          onSave={async (s) => {
            await setSchedule(s);
            qc.invalidateQueries({ queryKey: ["schedule"] });
            setShowSchedule(false);
          }}
          onClose={() => setShowSchedule(false)}
        />
      )}
      {showBulkAdd && (
        <BulkAddModal
          platforms={platforms}
          profiles={profiles}
          onClose={() => {
            setShowBulkAdd(false);
            qc.invalidateQueries({ queryKey: ["accounts"] });
            qc.invalidateQueries({ queryKey: ["profiles"] });
          }}
        />
      )}
      {showRefreshModal && (
        <RefreshAllModal
          accounts={allAccounts}
          profiles={profiles}
          platforms={platforms}
          hiddenPlatformValues={visibility?.hidden_platforms ?? []}
          hiddenProfileIds={visibility?.hidden_profile_ids ?? []}
          defaultIncludeHiddenPlatformAccounts={!!scheduleEffective.include_hidden_platform_accounts}
          defaultIncludeHiddenProfileAccounts={!!scheduleEffective.include_hidden_profile_accounts}
          progress={refreshProgress}
          lastReport={lastRefreshReport}
          lastDurationSec={lastRefreshDurationSec}
          onClose={() => setShowRefreshModal(false)}
          onStart={runSelectedRefresh}
          onCancel={() => refreshSelectionAbortRef.current?.abort()}
        />
      )}
      {deletingAccount && (
        <AccountDeleteDialog
          account={deletingAccount}
          isDeleting={deleteMutation.isPending}
          onCancel={() => setDeletingAccount(null)}
          onConfirm={() => deleteMutation.mutate(deletingAccount.id)}
        />
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 sm:flex-none px-5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active ? "bg-white text-black" : "text-zinc-400 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

function FilterBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border ${
        active
          ? "bg-white border-white text-black"
          : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}

function PlatformFilterChip({
  active,
  platform,
  label,
  onClick,
  onHide,
  hidden = false,
}: {
  active: boolean;
  platform: string;
  label: string;
  onClick: () => void;
  onHide: () => void;
  hidden?: boolean;
}) {
  return (
    <div className="relative group">
      <FilterBtn active={active} onClick={onClick}>
        <PlatformIcon platform={platform} className="w-3.5 h-3.5 inline-block mr-1 -mt-0.5" />
        {label}
      </FilterBtn>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onHide();
        }}
        title={hidden ? "Показать платформу" : "Скрыть платформу"}
        className={`absolute -top-1 -right-1 h-4 w-4 rounded-full border hidden group-hover:inline-flex items-center justify-center transition-colors ${
          hidden
            ? "border-emerald-300 bg-emerald-300/20 text-emerald-100 hover:bg-emerald-300/30"
            : "border-red-400/70 bg-red-500/15 text-red-300 hover:bg-red-500/25"
        }`}
      >
        <EyeIcon crossed={!hidden} className="w-2.5 h-2.5" />
      </button>
    </div>
  );
}

function PlatformIconFilterBtn({
  active,
  onClick,
  platform,
  label,
  hidden = false,
  onToggleHidden,
}: {
  active: boolean;
  onClick: () => void;
  platform: string;
  label: string;
  hidden?: boolean;
  onToggleHidden?: () => void;
}) {
  return (
    <div className="relative group">
      <button
        type="button"
        onClick={onClick}
        title={label}
        aria-label={label}
        className={`h-8 w-8 rounded-lg border inline-flex items-center justify-center transition-colors ${
          active
            ? "bg-white border-white text-black"
            : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
        } ${hidden ? "opacity-70" : ""}`}
      >
        <PlatformIcon platform={platform} className="w-4 h-4" />
      </button>
      {onToggleHidden && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleHidden();
          }}
          title={hidden ? "Показать платформу" : "Скрыть платформу"}
          className={`absolute -top-1 -right-1 h-4 w-4 rounded-full border hidden sm:inline-flex items-center justify-center transition-colors ${
            hidden
              ? "border-emerald-300 bg-emerald-300/20 text-emerald-100 hover:bg-emerald-300/30"
              : "border-red-400/70 bg-red-500/15 text-red-300 hover:bg-red-500/25"
          }`}
        >
          <EyeIcon crossed={!hidden} className="w-2.5 h-2.5" />
        </button>
      )}
    </div>
  );
}

function EyeIcon({ crossed = false, className = "w-4 h-4" }: { crossed?: boolean; className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M1.5 12s3.5-7 10.5-7 10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12z" />
      <circle cx="12" cy="12" r="3" />
      {crossed && <path strokeLinecap="round" strokeLinejoin="round" d="M3 3l18 18" />}
    </svg>
  );
}

function Th({ children, align = "left" }: { children?: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th className={`py-2.5 px-4 text-xs font-medium text-zinc-500 uppercase tracking-wide whitespace-nowrap ${align === "right" ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function SortableTh({
  children,
  align = "left",
  active,
  order,
  onClick,
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  active: boolean;
  order: SortOrder;
  onClick: () => void;
}) {
  return (
    <th className={`py-2.5 px-4 text-xs font-medium uppercase tracking-wide whitespace-nowrap ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex items-center gap-1 transition-colors ${active ? "text-zinc-200" : "text-zinc-500 hover:text-zinc-300"}`}
      >
        <span>{children}</span>
        <span className={active ? "text-zinc-300" : "text-zinc-600"}>
          {active ? (order === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}

function StatCell({ value, delta }: { value: number; delta: number | null }) {
  if (!value) return <span className="text-zinc-700 text-sm">—</span>;
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-zinc-200 font-medium text-sm">{fmt(value)}</span>
      {delta != null && delta !== 0 && (
        <span className={`text-xs ${delta > 0 ? "text-emerald-400" : "text-red-400"}`}>
          {fmtDelta(delta)}
        </span>
      )}
    </div>
  );
}

function AccountRow({ account, onDelete, onRefresh, isAutoRefreshing = false }: {
  account: Account; onDelete: () => void; onRefresh: () => void; isAutoRefreshing?: boolean;
}) {
  const PLATFORM_COLORS: Record<string, string> = {
    tiktok:   "text-[#fe2c55]", instagram: "text-pink-400",
    youtube:  "text-red-500",   telegram:  "text-blue-400",
    x:        "text-zinc-200",  threads:   "text-zinc-400",
    facebook: "text-[#1877F2]",
    rumble:   "text-[#85c742]",
  };
  const color = PLATFORM_COLORS[account.platform] ?? "text-zinc-300";
  const navigate = useNavigate();

  const refreshMutation = useMutation({
    mutationFn: () => refreshAccount(account.id),
    onSuccess: onRefresh,
  });

  return (
    <tr
      className="border-b border-zinc-800 last:border-0 hover:bg-zinc-900/70 cursor-pointer transition-colors group"
      onClick={() => navigate(`/accounts/${account.id}`)}
    >
      {/* Account */}
      <td className="py-3 px-4">
        <div className="flex items-center gap-3">
          {/* Avatar: always render via proxy to avoid CDN expiry; platform icon as fallback */}
          <div className="relative w-8 h-8 rounded-full overflow-hidden shrink-0 bg-zinc-800 flex items-center justify-center">
            <PlatformIcon platform={account.platform} className="w-4 h-4 text-zinc-500 absolute" />
            {account.avatar_url && (
              <img
                src={`/api/accounts/${account.id}/avatar/?v=${encodeURIComponent(account.avatar_url)}`}
                alt=""
                className="absolute inset-0 w-full h-full object-cover"
                onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
              />
            )}
          </div>
          <div className="min-w-0 flex flex-col gap-0.5">
            <p className="text-sm font-medium text-white truncate max-w-[180px]">
              {account.display_name || account.username}
            </p>
            <p className="text-xs text-zinc-500 truncate max-w-[180px]">{displayHandle(account.platform, account.username)}</p>
            {account.profile_unavailable && (
              <span className="text-[10px] font-medium w-fit px-1.5 py-0.5 rounded border border-amber-700/60 bg-amber-950/50 text-amber-200">
                Недоступен на площадке
              </span>
            )}
          </div>
        </div>
      </td>

      {/* Platform */}
      <td className="py-3 px-4 whitespace-nowrap">
        <span className={`flex items-center gap-1.5 text-xs font-medium ${color}`} title={account.platform_label}>
          <PlatformIcon platform={account.platform} className="w-3.5 h-3.5 shrink-0" />
          <span className="hidden lg:inline">{account.platform_label}</span>
        </span>
      </td>

      {/* Profile */}
      <td className="py-3 px-4">
        {account.profile_name ? (
          <span
            className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-md whitespace-nowrap"
            style={{ background: `${account.profile_color}22`, color: account.profile_color ?? "#aaa" }}
          >
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: account.profile_color ?? "#aaa" }} />
            {account.profile_name}
          </span>
        ) : (
          <span className="text-zinc-700 text-sm">—</span>
        )}
      </td>

      {/* Stats */}
      <td className="py-3 px-4 text-right"><StatCell value={account.follower_count} delta={account.follower_delta} /></td>
      <td className="py-3 px-4 text-right"><StatCell value={account.view_count}     delta={account.view_delta}     /></td>
      <td className="py-3 px-4 text-right"><StatCell value={account.like_count}     delta={account.like_delta}     /></td>
      <td className="py-3 px-4 text-right"><StatCell value={account.post_count}     delta={account.post_delta}     /></td>

      {/* Updated */}
      <td className="py-3 px-4 whitespace-nowrap">
        <span className="text-zinc-600 text-xs">{fmtDate(account.updated_at)}</span>
      </td>

      {/* Actions */}
      <td className="py-3 px-4" onClick={e => e.stopPropagation()}>
        {/* Auto-refresh spinner (shown instead of action buttons while loading after creation) */}
        {isAutoRefreshing ? (
          <div className="flex items-center justify-end gap-1.5 text-zinc-500 text-xs">
            <RefreshIcon spinning />
            <span>загрузка…</span>
          </div>
        ) : (
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity justify-end">
            <button
              onClick={() => {
                if (refreshMutation.isPending) return;
                refreshMutation.mutate();
              }}
              disabled={refreshMutation.isPending}
              className="text-zinc-500 hover:text-zinc-200 disabled:opacity-40 p-1.5 rounded-lg hover:bg-zinc-800 transition-colors"
              title="Обновить"
            >
              <RefreshIcon spinning={refreshMutation.isPending} />
            </button>
            <button
              onClick={onDelete}
              className="text-zinc-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-zinc-800 transition-colors"
              title="Удалить"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}
        {refreshMutation.isError && (
          <p className="text-red-400 text-xs text-right">
            {(refreshMutation.error as any)?.response?.data?.detail || "Ошибка"}
          </p>
        )}
      </td>
    </tr>
  );
}

function MobileAccountCard({ account, onDelete, onRefresh, isAutoRefreshing = false }: {
  account: Account; onDelete: () => void; onRefresh: () => void; isAutoRefreshing?: boolean;
}) {
  const navigate = useNavigate();
  const refreshMutation = useMutation({
    mutationFn: () => refreshAccount(account.id),
    onSuccess: onRefresh,
  });
  return (
    <div
      className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-2.5 space-y-2"
      onClick={() => navigate(`/accounts/${account.id}`)}
    >
      <div className="flex items-center gap-2">
        <div className="relative w-7 h-7 rounded-full overflow-hidden shrink-0 bg-zinc-800 flex items-center justify-center">
          <PlatformIcon platform={account.platform} className="w-4 h-4 text-zinc-500 absolute" />
          {account.avatar_url && (
            <img
              src={`/api/accounts/${account.id}/avatar/?v=${encodeURIComponent(account.avatar_url)}`}
              alt=""
              className="absolute inset-0 w-full h-full object-cover"
              onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-white truncate">{account.display_name || account.username}</p>
          <p className="text-[11px] text-zinc-500 truncate">{displayHandle(account.platform, account.username)}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {account.profile_color && (
            <span
              className="w-2 h-2 rounded-full border border-zinc-600/70"
              style={{ background: account.profile_color }}
              title="Цвет профиля"
            />
          )}
          {account.profile_unavailable && (
            <span className="text-[10px] font-semibold px-1 py-0.5 rounded border border-amber-700/60 bg-amber-950/50 text-amber-200">
              НД
            </span>
          )}
          <PlatformIcon platform={account.platform} className="w-3.5 h-3.5 text-zinc-300" />
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (refreshMutation.isPending) return;
              refreshMutation.mutate();
            }}
            disabled={refreshMutation.isPending || isAutoRefreshing}
            className="h-7 w-7 inline-flex items-center justify-center text-zinc-400 hover:text-zinc-100 disabled:opacity-40 rounded-lg hover:bg-zinc-800 transition-colors"
            title="Обновить"
          >
            <RefreshIcon spinning={refreshMutation.isPending || isAutoRefreshing} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="h-7 w-7 inline-flex items-center justify-center text-zinc-400 hover:text-red-400 rounded-lg hover:bg-zinc-800 transition-colors"
            title="Удалить"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-1.5 text-[11px]">
        <div title="Подписчики" className="rounded-md bg-zinc-900 border border-zinc-800 px-1.5 py-1 text-center text-zinc-100 font-medium tabular-nums">{fmt(account.follower_count)}</div>
        <div title="Просмотры" className="rounded-md bg-zinc-900 border border-zinc-800 px-1.5 py-1 text-center text-zinc-100 font-medium tabular-nums">{fmt(account.view_count)}</div>
        <div title="Лайки" className="rounded-md bg-zinc-900 border border-zinc-800 px-1.5 py-1 text-center text-zinc-100 font-medium tabular-nums">{fmt(account.like_count)}</div>
        <div title="Публикации" className="rounded-md bg-zinc-900 border border-zinc-800 px-1.5 py-1 text-center text-zinc-100 font-medium tabular-nums">{fmt(account.post_count)}</div>
      </div>
      <div className="flex items-center justify-between text-[11px] text-zinc-500">
        <span>{fmtDate(account.updated_at)}</span>
        <span className="inline-flex items-center gap-1">
          {account.profile_color ? (
            <span className="w-2 h-2 rounded-full border border-zinc-600/70" style={{ background: account.profile_color }} />
          ) : (
            <span className="text-zinc-600">—</span>
          )}
        </span>
      </div>
    </div>
  );
}


function RefreshIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg className={`w-4 h-4 ${spinning ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    </svg>
  );
}

function AccountDeleteDialog({
  account,
  isDeleting,
  onConfirm,
  onCancel,
}: {
  account: Account;
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
      onClick={(e) => e.target === e.currentTarget && !isDeleting && onCancel()}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-sm space-y-4">
        <h3 className="font-semibold text-white text-base">Удалить аккаунт?</h3>
        <p className="text-zinc-400 text-sm">
          Аккаунт <span className="text-white font-medium">{displayHandle(account.platform, account.username)}</span>{" "}
          будет удален из списка.
        </p>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isDeleting}
            className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300 disabled:opacity-40"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="px-4 py-2 rounded-xl bg-red-900/60 hover:bg-red-900 border border-red-800 text-red-200 text-sm font-medium disabled:opacity-40"
          >
            {isDeleting ? "Удаляю…" : "Удалить"}
          </button>
        </div>
      </div>
    </div>
  );
}

const REFRESH_MODAL_NO_PROFILE_KEY = "none";

function RefreshAllModal({
  accounts,
  profiles,
  platforms,
  hiddenPlatformValues,
  hiddenProfileIds,
  defaultIncludeHiddenPlatformAccounts,
  defaultIncludeHiddenProfileAccounts,
  progress,
  lastReport,
  lastDurationSec,
  onClose,
  onStart,
  onCancel,
}: {
  accounts: Account[];
  profiles: Profile[];
  platforms: Platform[];
  hiddenPlatformValues: string[];
  hiddenProfileIds: number[];
  defaultIncludeHiddenPlatformAccounts: boolean;
  defaultIncludeHiddenProfileAccounts: boolean;
  progress: { done: number; total: number; busyHint?: string | null; activeLabel?: string | null };
  lastReport: RefreshReportRow[] | null;
  lastDurationSec: number | null;
  onClose: () => void;
  onStart: (accountIds: number[], downloadCsv: boolean) => Promise<boolean>;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [selectedProfileKeys, setSelectedProfileKeys] = useState<string[]>([]);
  const [availabilityFilter, setAvailabilityFilter] = useState<"all" | "available" | "unavailable">("all");
  const [includeHiddenPlatforms, setIncludeHiddenPlatforms] = useState(defaultIncludeHiddenPlatformAccounts);
  const [includeHiddenProfiles, setIncludeHiddenProfiles] = useState(defaultIncludeHiddenProfileAccounts);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [downloadCsv, setDownloadCsv] = useState(false);
  const [search, setSearch] = useState("");
  const [sortByUpdatedAsc, setSortByUpdatedAsc] = useState(true);
  const [running, setRunning] = useState(false);
  const [ioBusy, setIoBusy] = useState(false);
  const [ioNote, setIoNote] = useState<string | null>(null);
  const [ioErrors, setIoErrors] = useState<Array<{ section: string; row: number; message: string }>>([]);

  const hasUnassignedAccounts = useMemo(
    () => accounts.some((a) => a.profile_id == null),
    [accounts],
  );
  const unavailableCount = useMemo(
    () => accounts.filter((a) => !!a.profile_unavailable).length,
    [accounts],
  );
  const availableCount = Math.max(0, accounts.length - unavailableCount);
  const hiddenPlatformSet = useMemo(
    () => new Set((hiddenPlatformValues ?? []).map((v) => v.toLowerCase())),
    [hiddenPlatformValues],
  );
  const hiddenProfileSet = useMemo(
    () => new Set(hiddenProfileIds ?? []),
    [hiddenProfileIds],
  );

  const visibleAccounts = useMemo(() => {
    const filtered = accounts.filter((a) => {
      if (!includeHiddenPlatforms && hiddenPlatformSet.has(a.platform.toLowerCase())) return false;
      if (!includeHiddenProfiles && a.profile_id != null && hiddenProfileSet.has(a.profile_id)) return false;
      if (selectedPlatforms.length && !selectedPlatforms.includes(a.platform)) return false;
      if (availabilityFilter === "available" && a.profile_unavailable) return false;
      if (availabilityFilter === "unavailable" && !a.profile_unavailable) return false;
      if (selectedProfileKeys.length) {
        const wantNone = selectedProfileKeys.includes(REFRESH_MODAL_NO_PROFILE_KEY);
        const wantIds = selectedProfileKeys
          .filter((k) => k !== REFRESH_MODAL_NO_PROFILE_KEY)
          .map(Number);
        const matchNone = a.profile_id == null && wantNone;
        const matchProfile = a.profile_id != null && wantIds.includes(a.profile_id);
        if (!matchNone && !matchProfile) return false;
      }
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          a.username.toLowerCase().includes(q) ||
          (a.display_name || "").toLowerCase().includes(q) ||
          (a.profile_name || "").toLowerCase().includes(q)
        );
      }
      return true;
    });
    filtered.sort((a, b) => {
      const av = new Date(a.updated_at).getTime();
      const bv = new Date(b.updated_at).getTime();
      return sortByUpdatedAsc ? av - bv : bv - av;
    });
    return filtered;
  }, [
    accounts,
    search,
    selectedPlatforms,
    selectedProfileKeys,
    availabilityFilter,
    sortByUpdatedAsc,
    includeHiddenPlatforms,
    includeHiddenProfiles,
    hiddenPlatformSet,
    hiddenProfileSet,
  ]);

  useEffect(() => {
    setSelectedIds(visibleAccounts.map((a) => a.id));
  }, [includeHiddenPlatforms, includeHiddenProfiles]);

  const togglePlatform = (p: string) => {
    setSelectedPlatforms((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]);
  };

  const toggleProfileKey = (key: string) => {
    setSelectedProfileKeys((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));
  };

  useEffect(() => {
    const visibleIds = new Set(visibleAccounts.map((a) => a.id));
    setSelectedIds((prev) => prev.filter((id) => visibleIds.has(id)));
  }, [visibleAccounts]);

  const allVisibleSelected = visibleAccounts.length > 0 && visibleAccounts.every((a) => selectedIds.includes(a.id));
  const progressPercent = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const busyHint = progress.busyHint ?? null;
  const activeLabel = progress.activeLabel ?? null;
  const failedIds = useMemo(
    () => (lastReport ?? []).filter((r) => r.status === "ошибка").map((r) => r.id),
    [lastReport],
  );
  const showIndeterminate =
    progress.total > 0 &&
    progressPercent === 0 &&
    (Boolean(busyHint) || Boolean(activeLabel));

  const handleExportSnapshot = async () => {
    setIoBusy(true);
    setIoNote(null);
    setIoErrors([]);
    try {
      await downloadSnapshotExport();
      setIoNote("Файл CSV с полным снимком сохранён.");
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setIoNote(d || "Ошибка экспорта");
    } finally {
      setIoBusy(false);
    }
  };

  const handleImportSnapshot = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setIoBusy(true);
    setIoNote(null);
    setIoErrors([]);
    try {
      const r = await importSnapshotFile(f);
      await qc.invalidateQueries({ queryKey: ["accounts"] });
      await qc.invalidateQueries({ queryKey: ["profiles"] });
      await qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "account" || q.queryKey[0] === "account-posts" });
      const errn = r.errors?.length ?? 0;
      setIoErrors(r.errors ?? []);
      const accSnaps = r.account_snapshots_upserted ?? 0;
      const postSnaps = r.post_snapshots_upserted ?? 0;
      setIoNote(
        `Импорт: аккаунты +${r.accounts_created}/обновлено ${r.accounts_updated}, посты +${r.posts_created}/обновлено ${r.posts_updated}` +
          ` · snapshots: аккаунтов ${accSnaps}, постов ${postSnaps}` +
          (errn ? ` · ошибок по строкам: ${errn}` : ""),
      );
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setIoNote(d || "Ошибка импорта");
      setIoErrors([]);
    } finally {
      setIoBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm sm:px-4" onClick={(e) => e.target === e.currentTarget && !running && !ioBusy && onClose()}>
      <div className="bg-zinc-900 border border-zinc-700 rounded-t-2xl sm:rounded-2xl p-3 sm:p-6 w-full sm:max-w-3xl h-[88dvh] sm:h-auto sm:max-h-[90vh] flex flex-col gap-3 sm:gap-4">
        <div className="flex items-start justify-between gap-2 sm:gap-3 flex-wrap">
          <h3 className="text-white font-semibold shrink-0">Обновить выбранные аккаунты</h3>
          <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap justify-end">
            <button
              type="button"
              disabled={running || ioBusy}
              onClick={() => void handleExportSnapshot()}
              className="text-xs px-2.5 sm:px-3 py-1.5 rounded-lg border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
            >
              Экспорт CSV
            </button>
            <button
              type="button"
              disabled={running || ioBusy}
              onClick={() => fileRef.current?.click()}
              className="text-xs px-2.5 sm:px-3 py-1.5 rounded-lg border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
            >
              Импорт CSV
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={handleImportSnapshot}
            />
            {!running && <button type="button" onClick={onClose} className="text-zinc-500 hover:text-white text-xl leading-none">×</button>}
          </div>
        </div>
        {ioNote && <p className="text-xs text-zinc-400">{ioNote}</p>}
        {ioErrors.length > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5">
            <p className="text-xs text-amber-200 font-medium mb-1">Ошибки импорта:</p>
            <div className="max-h-28 overflow-y-auto pr-1">
              {ioErrors.map((err, idx) => (
                <p key={`${err.section}-${err.row}-${idx}`} className="text-[11px] text-amber-100/90">
                  [{err.section || "FILE"} / строка {err.row}] {err.message}
                </p>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-1.5 sm:gap-2">
          {platforms.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => togglePlatform(p.value)}
              title={p.label}
              className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs border ${selectedPlatforms.includes(p.value) ? "bg-white text-black border-white" : "border-zinc-700 text-zinc-400 hover:text-white"}`}
            >
              <PlatformIcon platform={p.value} className="w-3.5 h-3.5 shrink-0" />
              <span className="hidden sm:inline">{p.label}</span>
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-zinc-800/90 bg-zinc-950/35 px-3 py-2.5 space-y-2">
          <label className="flex items-center justify-between gap-3 text-sm text-zinc-300">
            <span>Включать аккаунты скрытых платформ</span>
            <input
              type="checkbox"
              checked={includeHiddenPlatforms}
              onChange={(e) => setIncludeHiddenPlatforms(e.target.checked)}
              className="accent-zinc-200 h-4 w-4"
            />
          </label>
          <label className="flex items-center justify-between gap-3 text-sm text-zinc-300">
            <span>Включать аккаунты скрытых профилей</span>
            <input
              type="checkbox"
              checked={includeHiddenProfiles}
              onChange={(e) => setIncludeHiddenProfiles(e.target.checked)}
              className="accent-zinc-200 h-4 w-4"
            />
          </label>
        </div>

        {(profiles.length > 0 || hasUnassignedAccounts) && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] uppercase tracking-wide text-zinc-500">Профили</span>
            <div className="flex flex-wrap gap-2">
              {hasUnassignedAccounts && (
                <button
                  type="button"
                  onClick={() => toggleProfileKey(REFRESH_MODAL_NO_PROFILE_KEY)}
                  className={`px-2.5 py-1 rounded-lg text-xs border ${
                    selectedProfileKeys.includes(REFRESH_MODAL_NO_PROFILE_KEY)
                      ? "bg-white text-black border-white"
                      : "border-zinc-700 text-zinc-400 hover:text-white"
                  }`}
                >
                  Без профиля
                </button>
              )}
              {profiles.map((p) => {
                const key = String(p.id);
                const active = selectedProfileKeys.includes(key);
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => toggleProfileKey(key)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border ${
                      active ? "bg-white text-black border-white" : "border-zinc-700 text-zinc-400 hover:text-white"
                    }`}
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0 border border-zinc-600"
                      style={{ backgroundColor: p.color || "#71717a" }}
                      aria-hidden
                    />
                    {p.name}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] uppercase tracking-wide text-zinc-500">Доступность</span>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setAvailabilityFilter("all")}
              className={`px-2.5 py-1 rounded-lg text-xs border ${
                availabilityFilter === "all"
                  ? "bg-white text-black border-white"
                  : "border-zinc-700 text-zinc-400 hover:text-white"
              }`}
            >
              Все
            </button>
            <button
              type="button"
              onClick={() => setAvailabilityFilter("available")}
              className={`px-2.5 py-1 rounded-lg text-xs border ${
                availabilityFilter === "available"
                  ? "bg-white text-black border-white"
                  : "border-zinc-700 text-zinc-400 hover:text-white"
              }`}
            >
              Только доступные ({availableCount})
            </button>
            <button
              type="button"
              onClick={() => setAvailabilityFilter("unavailable")}
              className={`px-2.5 py-1 rounded-lg text-xs border ${
                availabilityFilter === "unavailable"
                  ? "bg-white text-black border-white"
                  : "border-zinc-700 text-zinc-400 hover:text-white"
              }`}
            >
              Только недоступные ({unavailableCount})
            </button>
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap sm:flex-nowrap">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск: username, имя, профиль"
            className="min-w-[160px] flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-zinc-500"
          />
          <button
            type="button"
            onClick={() => {
              const ids = visibleAccounts.map((a) => a.id);
              setSelectedIds((prev) => allVisibleSelected ? prev.filter((id) => !ids.includes(id)) : Array.from(new Set([...prev, ...ids])));
            }}
            className="text-xs border border-zinc-700 rounded-lg px-2.5 py-2 text-zinc-300 hover:text-white whitespace-nowrap"
          >
            {allVisibleSelected ? "Снять все" : "Выбрать все"}
          </button>
          <button
            type="button"
            onClick={() => setSortByUpdatedAsc((v) => !v)}
            className="text-xs border border-zinc-700 rounded-lg px-2.5 py-2 text-zinc-300 hover:text-white whitespace-nowrap"
            title="Сортировка по времени обновления"
          >
            Обновление {sortByUpdatedAsc ? "↑" : "↓"}
          </button>
        </div>

        <div className="overflow-y-auto border border-zinc-800 rounded-xl divide-y divide-zinc-800 flex-1 min-h-[220px]">
          {visibleAccounts.map((a) => (
            <label key={a.id} className="flex items-center gap-2 px-2.5 sm:px-3 py-2 cursor-pointer hover:bg-zinc-800/50">
              <input
                type="checkbox"
                checked={selectedIds.includes(a.id)}
                onChange={(e) => setSelectedIds((prev) => e.target.checked ? [...prev, a.id] : prev.filter((id) => id !== a.id))}
                className="accent-zinc-200"
              />
              <span className="text-xs text-zinc-500 w-16 sm:w-20 truncate">{a.platform_label}</span>
              <a
                href={`/accounts/${a.id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-sm text-white hover:underline truncate max-w-[34vw] sm:max-w-none"
                title="Открыть аккаунт"
              >
                {a.display_name || a.username}
              </a>
              <a
                href={`/accounts/${a.id}`}
                onClick={(e) => e.stopPropagation()}
                className="hidden sm:inline text-xs text-zinc-500 hover:text-zinc-300 hover:underline"
                title="Открыть аккаунт"
              >
                {displayHandle(a.platform, a.username)}
              </a>
              <span className="ml-auto text-[11px] text-zinc-600 tabular-nums whitespace-nowrap" title="Последнее обновление">
                {fmtDate(a.updated_at)}
              </span>
            </label>
          ))}
          {visibleAccounts.length === 0 && <p className="p-4 text-sm text-zinc-500">Нет аккаунтов по выбранному фильтру.</p>}
        </div>

        {lastReport && lastReport.length > 0 && (
          <div className="border border-zinc-800 rounded-xl p-3 space-y-2 max-h-56 overflow-y-auto">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-xs uppercase tracking-wide text-zinc-500">Результаты последнего обновления</div>
              {lastDurationSec != null && (
                <span className="text-xs text-zinc-400">· {formatRefreshTotalDurationRu(lastDurationSec)}</span>
              )}
              {failedIds.length > 0 && (
                <button
                  type="button"
                  disabled={running}
                  onClick={async () => {
                    setRunning(true);
                    try {
                      await onStart(failedIds, false);
                    } finally {
                      setRunning(false);
                    }
                  }}
                  className="ml-auto text-xs px-2.5 py-1 rounded-lg border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
                >
                  Повторить ошибки ({failedIds.length})
                </button>
              )}
            </div>
            {lastReport.map((row) => {
              const canRetry = row.status === "ошибка";
              return (
                <div key={row.id} className="flex items-center gap-2 text-sm">
                  <PlatformIcon platform={row.platform} className="w-3.5 h-3.5 shrink-0" />
                  <button
                    type="button"
                    onClick={() => navigate(`/accounts/${row.id}`)}
                    className="text-zinc-200 hover:underline"
                    title="Открыть аккаунт"
                  >
                    {displayHandle(row.platform, row.username)}
                  </button>
                  <span className={`text-xs ${
                    row.status === "ошибка"
                      ? "text-red-400"
                      : row.status === "нет обновлений"
                        ? "text-amber-300"
                        : "text-emerald-400"
                  }`}
                  >
                    {row.status}
                  </span>
                  <span className="ml-auto text-xs text-zinc-500">
                    посты: {row.post_count}
                    {row.post_delta != null && row.post_delta !== 0 ? ` (${fmtDelta(row.post_delta)})` : ""}
                  </span>
                  {canRetry && (
                    <button
                      type="button"
                      disabled={running}
                      onClick={async () => {
                        setRunning(true);
                        try {
                          await onStart([row.id], false);
                        } finally {
                          setRunning(false);
                        }
                      }}
                      className="text-xs px-2 py-1 rounded-lg border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
                    >
                      Попробовать ещё раз
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input type="checkbox" checked={downloadCsv} onChange={(e) => setDownloadCsv(e.target.checked)} className="accent-zinc-200" />
          Скачать CSV после завершения
        </label>

        {running && (
          <div className="space-y-1.5">
            {activeLabel && (
              <p className="text-xs text-zinc-200 font-medium leading-snug" title={activeLabel}>
                Сейчас: {activeLabel}
              </p>
            )}
            <div className="flex justify-between text-xs text-zinc-400 gap-2">
              <span className="shrink-0">Завершено аккаунтов</span>
              <span className="text-right tabular-nums">
                {progress.done}/{progress.total}
                {progressPercent > 0 || progress.done >= progress.total ? ` · ${progressPercent}%` : " · ждём ответ…"}
              </span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden relative">
              {showIndeterminate ? (
                <div
                  className="absolute inset-y-0 w-1/3 max-w-[40%] bg-white/50 rounded-full animate-pulse"
                  style={{ left: "0%" }}
                  aria-hidden
                />
              ) : (
                <div className="h-full bg-white/90 transition-all" style={{ width: `${progressPercent}%` }} />
              )}
            </div>
            {busyHint && <p className="text-[11px] text-zinc-500 leading-snug">{busyHint}</p>}
          </div>
        )}

        <div className="flex justify-end flex-wrap gap-2 pt-1 border-t border-zinc-800 mt-auto">
          {!running && <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300">Закрыть</button>}
          {running && (
            <button
              type="button"
              onClick={() => onCancel()}
              className="px-4 py-2 text-sm rounded-xl border border-amber-600/80 text-amber-200 hover:bg-amber-950/50"
            >
              Остановить обновление
            </button>
          )}
          <button
            disabled={running || selectedIds.length === 0}
            onClick={async () => {
              setRunning(true);
              try {
                await onStart(selectedIds, downloadCsv);
              } finally {
                setRunning(false);
              }
            }}
            className="px-4 py-2 text-sm rounded-xl bg-white text-black font-semibold disabled:opacity-40"
          >
            {running ? "Обновляю…" : `Обновить (${selectedIds.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Schedule Modal ────────────────────────────────────────────────────────────

const INTERVAL_OPTIONS = [1, 2, 3, 4, 6, 8, 12, 24];
const TIME_PRESETS = ["06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "00:00"];

function AutoRefreshProgressCard({
  status,
  enabled,
  onOpenSettings,
}: {
  status?: AutoRefreshStatus;
  enabled: boolean;
  onOpenSettings?: () => void;
}) {
  const done = status?.processed_accounts ?? 0;
  const total = status?.total_accounts ?? 0;
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const running = !!status?.is_running;
  const statusLabel = running
    ? "Идёт автообновление"
    : enabled
      ? "Автообновление вкл"
      : "Автообновление выкл";
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-3 py-2 sm:px-3 sm:py-2">
      <div className="flex items-center gap-2 min-h-10">
        <span className={`h-2 w-2 shrink-0 rounded-full ${running ? "bg-emerald-400 animate-pulse" : enabled ? "bg-zinc-400" : "bg-zinc-700"}`} />
        <span className="text-xs sm:text-xs text-zinc-300 font-medium leading-tight">{statusLabel}</span>
        <span className="text-[11px] text-zinc-500 tabular-nums shrink-0">{done}/{total || 0}</span>
        {onOpenSettings && (
          <button
            type="button"
            onClick={onOpenSettings}
            className="ml-auto min-h-10 min-w-[4.75rem] -mr-2 px-3 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 transition-colors touch-manipulation active:bg-zinc-800"
          >
            Настроить
          </button>
        )}
      </div>
      <div className="mt-1.5 h-1 rounded-full bg-zinc-800 overflow-hidden">
        <div className="h-full bg-white/90 transition-all" style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-1 flex items-center gap-2 text-[10px] sm:text-[11px] text-zinc-500">
        <span className="tabular-nums">{percent}%</span>
        {status?.current_account && <span className="text-zinc-400 truncate">{status.current_account}</span>}
        {!!status?.failed_accounts && <span className="text-red-400 shrink-0">ошибок: {status.failed_accounts}</span>}
      </div>
    </div>
  );
}

function ScheduleModal({
  initial,
  scheduleLoadFailed,
  onRetryScheduleLoad,
  autoStatus,
  showAutoProgressWidget,
  onToggleAutoProgressWidget,
  onRunNow,
  runNowPending,
  onStopNow,
  stopNowPending,
  onSave,
  onClose,
}: {
  initial: RefreshSchedule;
  scheduleLoadFailed?: boolean;
  onRetryScheduleLoad?: () => void;
  autoStatus?: AutoRefreshStatus;
  showAutoProgressWidget: boolean;
  onToggleAutoProgressWidget: (value: boolean) => void;
  onRunNow: () => Promise<unknown>;
  runNowPending: boolean;
  onStopNow: () => Promise<unknown>;
  stopNowPending: boolean;
  onSave: (s: RefreshSchedule) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState<RefreshSchedule>({ ...initial });
  const [customTime, setCustomTime] = useState("");
  const [saving, setSaving] = useState(false);
  const [reportDownloading, setReportDownloading] = useState(false);

  useEffect(() => {
    setForm({ ...initial });
  }, [initial]);

  const toggleTime = (t: string) => {
    setForm(f => ({
      ...f,
      times: f.times.includes(t) ? f.times.filter(x => x !== t) : [...f.times, t].sort(),
    }));
  };

  const addCustomTime = () => {
    const t = customTime.trim();
    if (!t || form.times.includes(t)) return;
    try {
      const [h, m] = t.split(":").map(Number);
      if (h >= 0 && h <= 23 && m >= 0 && m <= 59) {
        const pad = (n: number) => String(n).padStart(2, "0");
        const norm = `${pad(h)}:${pad(m)}`;
        setForm(f => ({ ...f, times: [...f.times, norm].sort() }));
        setCustomTime("");
      }
    } catch { /* ignore */ }
  };

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(form); } finally { setSaving(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm px-3 pt-10 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-4 sm:pt-4 sm:pb-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-t-2xl sm:rounded-2xl p-4 sm:p-6 w-full max-w-md max-h-[min(92dvh,900px)] overflow-y-auto overscroll-contain space-y-4 sm:space-y-5 shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 sticky top-0 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 -mt-2 bg-zinc-900/95 border-b border-zinc-800/80 sm:border-0 sm:bg-transparent sm:static sm:p-0 z-10">
          <h2 className="font-semibold text-white text-base leading-tight pr-2">Расписание обновлений</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="min-h-11 min-w-11 shrink-0 inline-flex items-center justify-center rounded-xl text-zinc-500 hover:text-white hover:bg-zinc-800 transition-colors active:bg-zinc-800"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {scheduleLoadFailed && (
          <div className="rounded-xl border border-amber-800/90 bg-amber-950/35 px-3 py-2.5 text-xs text-amber-100 leading-snug space-y-2">
            <p>
              Настройки с сервера не загрузились (часто не применены миграции или ошибка БД). Ниже — значения по умолчанию;
              «Сохранить» отправит их на сервер.
            </p>
            {onRetryScheduleLoad && (
              <button
                type="button"
                onClick={() => onRetryScheduleLoad()}
                className="text-amber-200 underline font-medium hover:text-white"
              >
                Повторить загрузку
              </button>
            )}
          </div>
        )}

        {/* Enable toggle */}
        <label className="flex items-center justify-between gap-3 cursor-pointer min-h-12 py-1 touch-manipulation">
          <span className="text-sm text-zinc-300">Автообновление</span>
          <div
            role="switch"
            aria-checked={form.enabled}
            tabIndex={0}
            onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setForm(f => ({ ...f, enabled: !f.enabled }));
              }
            }}
            className={`shrink-0 w-12 h-7 rounded-full transition-colors relative cursor-pointer ${form.enabled ? "bg-emerald-500" : "bg-zinc-700"}`}
          >
            <span className={`absolute top-1 w-5 h-5 bg-white rounded-full transition-all shadow ${form.enabled ? "left-6" : "left-1"}`} />
          </div>
        </label>

        <div className="rounded-xl border border-zinc-800/90 bg-zinc-950/35 px-3 py-3 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer touch-manipulation py-0.5">
            <input
              type="checkbox"
              className="accent-emerald-400 mt-1 h-5 w-5 shrink-0 rounded border-zinc-600"
              checked={form.auto_refresh_csv_report ?? false}
              onChange={(e) =>
                setForm((f) => ({ ...f, auto_refresh_csv_report: e.target.checked }))
              }
            />
            <span className="text-sm text-zinc-300 leading-snug">
              После завершения автообновления (по расписанию или «Запустить сейчас») сохранять CSV-отчёт
            </span>
          </label>
          <p className="text-[11px] text-zinc-500 leading-snug pl-8 sm:pl-8">
            В отчёте — результат по каждому аккаунту и длительность всего прогона. Файл хранится на сервере; утром откройте это окно и нажмите «Скачать». Открытый браузер ночью не нужен.
          </p>
          <label className="flex items-start gap-3 cursor-pointer touch-manipulation py-0.5">
            <input
              type="checkbox"
              className="accent-emerald-400 mt-1 h-5 w-5 shrink-0 rounded border-zinc-600"
              checked={form.include_hidden_platform_accounts ?? false}
              onChange={(e) =>
                setForm((f) => ({ ...f, include_hidden_platform_accounts: e.target.checked }))
              }
            />
            <span className="text-sm text-zinc-300 leading-snug">
              В автообновлении учитывать аккаунты скрытых платформ
            </span>
          </label>
          <label className="flex items-start gap-3 cursor-pointer touch-manipulation py-0.5">
            <input
              type="checkbox"
              className="accent-emerald-400 mt-1 h-5 w-5 shrink-0 rounded border-zinc-600"
              checked={form.include_hidden_profile_accounts ?? false}
              onChange={(e) =>
                setForm((f) => ({ ...f, include_hidden_profile_accounts: e.target.checked }))
              }
            />
            <span className="text-sm text-zinc-300 leading-snug">
              В автообновлении учитывать аккаунты скрытых профилей
            </span>
          </label>
        </div>

        {form.enabled && (
          <>
            {/* Mode selector */}
            <div className="flex flex-col sm:flex-row gap-2">
              {(["interval", "times"] as const).map(m => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setForm(f => ({ ...f, mode: m }))}
                  className={`flex-1 min-h-12 px-3 rounded-xl text-sm font-medium border transition-colors touch-manipulation active:scale-[0.99] ${
                    form.mode === m ? "bg-white text-black border-white" : "border-zinc-700 text-zinc-400 hover:text-white active:bg-zinc-800"
                  }`}
                >
                  {m === "interval" ? "Каждые N часов" : "В определённое время"}
                </button>
              ))}
            </div>

            {/* Interval mode */}
            {form.mode === "interval" && (
              <div>
                <p className="text-xs text-zinc-500 mb-2">Интервал обновления</p>
                <div className="flex flex-wrap gap-2">
                  {INTERVAL_OPTIONS.map(h => (
                    <button
                      key={h}
                      type="button"
                      onClick={() => setForm(f => ({ ...f, interval_hours: h }))}
                      className={`min-h-11 px-4 py-2 rounded-xl text-sm font-medium border transition-colors touch-manipulation active:scale-[0.98] ${
                        form.interval_hours === h ? "bg-white text-black border-white" : "border-zinc-700 text-zinc-400 hover:text-white active:bg-zinc-800"
                      }`}
                    >{h}ч</button>
                  ))}
                </div>
              </div>
            )}

            {/* Times mode */}
            {form.mode === "times" && (
              <div>
                <p className="text-xs text-zinc-500 mb-2">Время обновления (МСК)</p>
                <div className="flex flex-wrap gap-2 mb-3">
                  {TIME_PRESETS.map(t => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => toggleTime(t)}
                      className={`min-h-11 px-3.5 py-2 rounded-xl text-sm font-medium border transition-colors touch-manipulation active:scale-[0.98] ${
                        form.times.includes(t) ? "bg-white text-black border-white" : "border-zinc-700 text-zinc-400 hover:text-white active:bg-zinc-800"
                      }`}
                    >{t}</button>
                  ))}
                </div>
                {/* Custom time slots */}
                {form.times.filter(t => !TIME_PRESETS.includes(t)).length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-3">
                    {form.times.filter(t => !TIME_PRESETS.includes(t)).map(t => (
                      <span key={t} className="flex items-center gap-1 min-h-11 px-2.5 py-2 rounded-xl text-sm bg-zinc-800 border border-zinc-600 text-zinc-300">
                        {t}
                        <button type="button" onClick={() => toggleTime(t)} className="min-w-10 min-h-10 -mr-1 inline-flex items-center justify-center text-zinc-500 hover:text-red-400 rounded-lg touch-manipulation">×</button>
                      </span>
                    ))}
                  </div>
                )}
                {/* Add custom */}
                <div className="flex flex-col sm:flex-row gap-2 sm:items-stretch">
                  <input
                    type="time"
                    value={customTime}
                    onChange={e => setCustomTime(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 min-h-12 py-2.5 text-base sm:text-sm text-white focus:outline-none focus:border-zinc-500 w-full sm:flex-1"
                    onKeyDown={e => e.key === "Enter" && addCustomTime()}
                  />
                  <button
                    type="button"
                    onClick={addCustomTime}
                    disabled={!customTime}
                    className="min-h-12 shrink-0 px-4 bg-zinc-800 border border-zinc-700 rounded-xl text-sm font-medium text-zinc-300 hover:text-white hover:bg-zinc-700 disabled:opacity-40 transition-colors touch-manipulation sm:w-auto w-full active:scale-[0.99]"
                  >
                    + Добавить
                  </button>
                </div>
                {form.times.length === 0 && (
                  <p className="text-xs text-zinc-600 mt-2">Выбери хотя бы одно время</p>
                )}
              </div>
            )}

            <div>
              <p className="text-xs text-zinc-500 mb-2">Пропускать недавно обновлённые</p>
              <div className="flex flex-wrap gap-2">
                {[0, 1, 3, 6, 12, 24].map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, skip_recent_hours: h }))}
                    className={`min-h-11 px-3 sm:px-3.5 py-2 rounded-xl text-sm font-medium border transition-colors touch-manipulation active:scale-[0.98] ${
                      (form.skip_recent_hours ?? 0) === h
                        ? "bg-white text-black border-white"
                        : "border-zinc-700 text-zinc-400 hover:text-white active:bg-zinc-800"
                    }`}
                  >
                    {h === 0 ? "Не пропускать" : `< ${h}ч`}
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-3 space-y-3">
              {autoStatus?.is_running ? (
                <button
                  type="button"
                  onClick={() => void onStopNow()}
                  disabled={stopNowPending || !!autoStatus?.cancel_requested}
                  className="w-full rounded-xl border border-amber-700/80 bg-amber-950/40 px-4 py-3.5 text-left text-sm leading-snug text-amber-200 hover:bg-amber-950/60 disabled:opacity-40 min-h-[3.25rem] touch-manipulation active:scale-[0.995]"
                >
                  {autoStatus?.cancel_requested
                    ? <>
                        <span className="font-medium block">Останавливаю…</span>
                        <span className="text-xs text-amber-200/80 mt-1 block">Текущий аккаунт завершится, новые не начнутся</span>
                      </>
                    : stopNowPending
                      ? "Отправляю остановку…"
                      : "Остановить автообновление"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void onRunNow()}
                  disabled={runNowPending}
                  className="w-full rounded-xl border border-zinc-600 bg-zinc-800 px-4 py-3.5 text-sm font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-40 min-h-12 touch-manipulation active:scale-[0.995]"
                >
                  {runNowPending ? "Запускаю…" : "Запустить автообновление сейчас"}
                </button>
              )}
              <label className="flex items-center justify-between gap-3 cursor-pointer min-h-12 py-1 touch-manipulation">
                <span className="text-sm text-zinc-300 leading-snug pr-2">Показывать прогресс на главной</span>
                <input
                  type="checkbox"
                  checked={showAutoProgressWidget}
                  onChange={(e) => onToggleAutoProgressWidget(e.target.checked)}
                  className="accent-emerald-400 h-5 w-5 shrink-0 rounded border-zinc-600"
                />
              </label>
              <AutoRefreshProgressCard
                status={autoStatus}
                enabled={form.enabled}
              />
            </div>
          </>
        )}

        {autoStatus?.has_csv_report && !autoStatus?.is_running && (
          <div className="rounded-xl border border-zinc-700/80 bg-zinc-950/50 px-3 py-3 space-y-2">
            <button
              type="button"
              disabled={reportDownloading}
              onClick={() => {
                setReportDownloading(true);
                void downloadAutoRefreshReport()
                  .catch((e: unknown) => {
                    window.alert(e instanceof Error ? e.message : "Не удалось скачать отчёт");
                  })
                  .finally(() => setReportDownloading(false));
              }}
              className="w-full rounded-xl border border-emerald-700/80 bg-emerald-950/35 px-4 py-3.5 text-left text-sm font-medium text-emerald-100 hover:bg-emerald-950/50 disabled:opacity-40 transition-colors min-h-[3.25rem] touch-manipulation active:scale-[0.995] leading-snug"
            >
              <span className="block sm:hidden">
                {reportDownloading ? "Скачиваю…" : "Скачать CSV-отчёт автообновления"}
              </span>
              <span className="hidden sm:block">
                {reportDownloading ? "Скачиваю…" : "Скачать отчёт последнего автообновления (CSV)"}
              </span>
            </button>
            {autoStatus?.report_generated_at && (
              <p className="text-[11px] text-zinc-500 leading-snug px-0.5">
                Сформировано:{" "}
                {new Date(autoStatus.report_generated_at).toLocaleString("ru-RU", {
                  dateStyle: "short",
                  timeStyle: "medium",
                })}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-col-reverse sm:flex-row gap-2 sm:gap-3 pt-1 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:pb-0">
          <button
            type="button"
            onClick={onClose}
            className="min-h-12 w-full sm:w-auto sm:min-w-[5.5rem] rounded-xl border border-zinc-700 bg-transparent px-4 text-sm font-medium text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors touch-manipulation active:scale-[0.995]"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || (form.enabled && form.mode === "times" && form.times.length === 0)}
            className="min-h-12 flex-1 bg-white text-black font-semibold py-3 rounded-xl text-sm disabled:opacity-40 hover:bg-zinc-100 transition-colors touch-manipulation active:scale-[0.995] shadow-sm"
          >
            {saving ? "Сохраняю…" : "Сохранить"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bulk Add Modal ────────────────────────────────────────────────────────────

interface ParsedAccount { platform: string; username: string; }
type BulkStatus = "pending" | "adding" | "done" | "duplicate" | "error";
interface BulkItem { raw: string; parsed: ParsedAccount | null; status: BulkStatus; message?: string; }

function parseAccountUrl(raw: string): ParsedAccount | null {
  const s = raw.trim();
  let m: RegExpMatchArray | null;

  m = s.match(/tiktok\.com\/@([\w.]+)/i);
  if (m) return { platform: "tiktok", username: m[1] };

  m = s.match(/youtube\.com\/@([\w.-]+)/i);
  if (m) return { platform: "youtube", username: m[1] };

  m = s.match(/instagram\.com\/([\w.]+)\/?(?:[?#]|$)/i);
  if (m && !["p", "reel", "tv", "explore", "stories"].includes(m[1]))
    return { platform: "instagram", username: m[1] };

  m = s.match(/(?:t|telegram)\.me\/([\w]+)/i);
  if (m) return { platform: "telegram", username: m[1] };

  m = s.match(/(?:twitter|x)\.com\/([\w]+)(?:$|[/?#])/i);
  if (m && !["home","explore","notifications","messages","i","settings"].includes(m[1].toLowerCase()))
    return { platform: "x", username: m[1] };

  m = s.match(/(?:www\.)?threads\.(?:net|com)\/@([\w.]+)/i);
  if (m) return { platform: "threads", username: m[1] };

  m = s.match(/(?:https?:\/\/)?(?:www\.|old\.|new\.)?reddit\.com\/r\/([A-Za-z0-9_]+)\/?(?:[?#].*)?$/i);
  if (m) return { platform: "reddit", username: m[1] };

  m = s.match(/rumble\.com\/(?:c|user)\/([\w.-]+)/i);
  if (m) return { platform: "rumble", username: m[1] };
  m = s.match(/rumble\.com\/([\w.-]+)/i);
  if (m) return { platform: "rumble", username: m[1] };

  // bare @handle with platform prefix: "@tiktok:handle", "@x:handle", etc.
  m = s.match(/^@?([\w.]+)$/);
  if (m && !s.includes('/')) return null; // ambiguous, skip

  return null;
}

function BulkAddModal({ platforms, profiles, onClose }: {
  platforms: Platform[];
  profiles: Profile[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [items, setItems] = useState<BulkItem[]>([]);
  const [profileId, setProfileId] = useState<string>("");
  const [running, setRunning] = useState(false);
  const abortRef = useRef(false);

  // Create-profile inline form state
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [newProfName, setNewProfName] = useState("");
  const [newProfColor, setNewProfColor] = useState("#6366f1");

  const createProfileMutation = useMutation({
    mutationFn: createProfile,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      setProfileId(String(created.id));
      setShowNewProfile(false);
      setNewProfName("");
      setNewProfColor("#6366f1");
    },
  });

  // Parse URLs as user types
  useEffect(() => {
    const lines = text.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    setItems(lines.map(raw => ({ raw, parsed: parseAccountUrl(raw), status: "pending" as BulkStatus })));
  }, [text]);

  const validItems = items.filter(i => i.parsed);
  const doneCount = items.filter(i => i.status === "done").length;
  const running_ = running;

  const startAdding = async () => {
    abortRef.current = false;
    setRunning(true);

    for (let i = 0; i < items.length; i++) {
      if (abortRef.current) break;
      const item = items[i];
      if (!item.parsed || item.status === "done") continue;

      setItems(prev => prev.map((x, idx) => idx === i ? { ...x, status: "adding" } : x));

      try {
        const acc = await createAccount({
          username: item.parsed.username,
          platform: item.parsed.platform,
          profile_id: profileId ? Number(profileId) : null,
        });
        setItems(prev => prev.map((x, idx) => idx === i ? { ...x, status: "done" } : x));
        // Refresh in background
        refreshAccount(acc.id).catch(() => {});
      } catch (err: any) {
        const status = err?.response?.status;
        if (status === 400 || status === 409) {
          const msg = err?.response?.data?.detail || "Уже существует";
          setItems(prev => prev.map((x, idx) => idx === i ? { ...x, status: "duplicate", message: msg } : x));
        } else {
          const msg = err?.response?.data?.detail || "Ошибка";
          setItems(prev => prev.map((x, idx) => idx === i ? { ...x, status: "error", message: msg } : x));
        }
      }
    }
    setRunning(false);
  };

  const STATUS_ICON: Record<BulkStatus, React.ReactNode> = {
    pending:   <span className="text-zinc-600 text-xs">—</span>,
    adding:    <span className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin inline-block" />,
    done:      <span className="text-emerald-400 text-xs font-bold">✓</span>,
    duplicate: <span className="text-yellow-400 text-xs">!</span>,
    error:     <span className="text-red-400 text-xs font-bold">✗</span>,
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4" onClick={e => e.target === e.currentTarget && !running_ && onClose()}>
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-lg flex flex-col gap-4 max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between shrink-0">
          <h2 className="font-semibold text-white text-base">Добавить список аккаунтов</h2>
          {!running_ && (
            <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Input */}
        {!running_ && doneCount === 0 && (
          <div className="shrink-0">
            <label className="block text-xs text-zinc-500 mb-1.5">
              Вставь URL аккаунтов — по одному на строку или через запятую
            </label>
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder={"https://www.tiktok.com/@username\nhttps://www.youtube.com/@channel\nhttps://www.threads.com/@user\nhttps://t.me/channel"}
              rows={5}
              autoFocus
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-500 resize-none font-mono"
            />
          </div>
        )}

        {/* Profile selector */}
        {!running_ && doneCount === 0 && (
          <div className="flex flex-col gap-2 shrink-0">
            <div className="flex items-center gap-2">
              <label className="text-xs text-zinc-500 shrink-0">Профиль:</label>
              <select
                value={profileId}
                onChange={e => setProfileId(e.target.value)}
                className="bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-zinc-500"
              >
                <option value="">Без профиля</option>
                {profiles.map(p => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
              </select>
              <button
                type="button"
                onClick={() => setShowNewProfile(v => !v)}
                title="Создать новый профиль"
                className="w-7 h-7 flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white transition-colors text-base leading-none"
              >
                {showNewProfile ? "×" : "+"}
              </button>
            </div>

            {/* Inline create-profile form */}
            {showNewProfile && (
              <div className="bg-zinc-800 border border-zinc-700 rounded-xl p-3 flex flex-col gap-2">
                <input
                  value={newProfName}
                  onChange={e => setNewProfName(e.target.value)}
                  placeholder="Название профиля"
                  autoFocus
                  className="w-full bg-zinc-900 border border-zinc-700 rounded px-2.5 py-1.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                  onKeyDown={e => {
                    if (e.key === "Enter" && newProfName.trim()) createProfileMutation.mutate({ name: newProfName.trim(), description: "", color: newProfColor, avatar_url: "" });
                    if (e.key === "Escape") setShowNewProfile(false);
                  }}
                />
                <div className="flex gap-1.5 flex-wrap">
                  {PRESET_COLORS.map(c => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setNewProfColor(c)}
                      className={`w-5 h-5 rounded-full border transition-transform ${newProfColor === c ? "border-white scale-125" : "border-transparent hover:scale-110"}`}
                      style={{ background: c }}
                    />
                  ))}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => createProfileMutation.mutate({ name: newProfName.trim(), description: "", color: newProfColor, avatar_url: "" })}
                    disabled={!newProfName.trim() || createProfileMutation.isPending}
                    className="flex-1 bg-white text-black text-xs font-semibold py-1.5 rounded-lg disabled:opacity-40 hover:bg-zinc-100 transition-colors"
                  >
                    {createProfileMutation.isPending ? "…" : "Создать"}
                  </button>
                  <button
                    onClick={() => setShowNewProfile(false)}
                    className="text-zinc-500 hover:text-zinc-300 text-xs px-3 py-1.5 rounded-lg transition-colors"
                  >
                    Отмена
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Parsed list */}
        {items.length > 0 && (
          <div className="overflow-y-auto flex-1 min-h-0 border border-zinc-800 rounded-xl divide-y divide-zinc-800">
            {items.map((item, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2">
                <span className="w-4 shrink-0 flex justify-center">{STATUS_ICON[item.status]}</span>
                {item.parsed ? (
                  <>
                    <PlatformIcon platform={item.parsed.platform} className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
                    <span className="text-sm text-zinc-300 flex-1 truncate">@{item.parsed.username}</span>
                    <span className="text-xs text-zinc-600 shrink-0">{platforms.find(p => p.value === item.parsed!.platform)?.label}</span>
                  </>
                ) : (
                  <>
                    <span className="text-sm text-zinc-600 flex-1 truncate">{item.raw}</span>
                    <span className="text-xs text-red-400 shrink-0">Не распознан</span>
                  </>
                )}
                {item.message && <span className="text-xs text-yellow-400 shrink-0 ml-1">{item.message}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Summary */}
        {items.length > 0 && (
          <p className="text-xs text-zinc-500 shrink-0">
            Распознано: <span className="text-white">{validItems.length}</span> из {items.length}
            {doneCount > 0 && <span className="text-emerald-400 ml-2">· Добавлено: {doneCount}</span>}
          </p>
        )}

        {/* Actions */}
        <div className="flex gap-2 shrink-0">
          {!running_ && doneCount < validItems.length && validItems.length > 0 && (
            <button
              onClick={startAdding}
              className="flex-1 bg-white text-black font-semibold py-2 rounded-xl text-sm hover:bg-zinc-100 transition-colors"
            >
              Добавить {validItems.length} {validItems.length === 1 ? "аккаунт" : validItems.length < 5 ? "аккаунта" : "аккаунтов"}
            </button>
          )}
          {running_ && (
            <button
              onClick={() => { abortRef.current = true; }}
              className="flex-1 bg-red-900/60 border border-red-800 text-red-300 font-semibold py-2 rounded-xl text-sm hover:bg-red-900 transition-colors"
            >
              Остановить
            </button>
          )}
          {!running_ && (
            <button onClick={onClose} className="px-4 py-2 text-zinc-500 hover:text-zinc-300 text-sm transition-colors">
              {doneCount > 0 ? "Готово" : "Отмена"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
