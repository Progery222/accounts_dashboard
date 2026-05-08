import { apiClient } from "./client";

export interface Account {
  id: number;
  username: string;
  platform: string;
  platform_label: string;
  profile_id: number | null;
  profile_name: string | null;
  profile_color: string | null;
  display_name: string;
  avatar_url: string;
  bio: string;
  follower_count: number;
  like_count: number;
  view_count: number;
  post_count: number;
  /** Instagram и др.: последнее обновление зафиксировало удалённый/недоступный профиль */
  profile_unavailable?: boolean;
  is_platform_hidden?: boolean;
  is_profile_hidden?: boolean;
  follower_delta: number | null;
  like_delta: number | null;
  view_delta: number | null;
  post_delta: number | null;
  created_at: string;
  updated_at: string;
}

export interface Platform {
  value: string;
  label: string;
  hidden?: boolean;
}

export interface Post {
  id: number;
  external_id: string;
  description: string;
  hashtags: string[];
  thumbnail_url: string;
  post_url: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  view_delta: number | null;
  like_delta: number | null;
  comment_delta: number | null;
  posted_at: string | null;
  updated_at: string;
}

export interface RefreshAllResult {
  refreshed: number;
  failed: number;
  errors: string[];
  report: Array<{
    id: number;
    platform: string;
    username: string;
    status: string;
    follower_count: number;
    follower_delta: number | null;
    like_count: number;
    like_delta: number | null;
    view_count: number;
    view_delta: number | null;
    post_count: number;
    post_delta: number | null;
    error?: string;
  }>;
}

export interface AccountsFilter {
  platform?: string;
  profile_id?: number | "none";
  search?: string;
  include_hidden?: boolean;
  include_hidden_platforms?: boolean;
  include_hidden_profiles?: boolean;
}

export async function getAccounts(filter: AccountsFilter = {}): Promise<Account[]> {
  const { data } = await apiClient.get<Account[]>("/api/accounts/", { params: filter });
  return data;
}

export async function createAccount(account: Partial<Account>): Promise<Account> {
  const { data } = await apiClient.post<Account>("/api/accounts/", account);
  return data;
}

export async function updateAccount(id: number, account: Partial<Account>): Promise<Account> {
  const { data } = await apiClient.patch<Account>(`/api/accounts/${id}/`, account);
  return data;
}

export async function deleteAccount(id: number): Promise<void> {
  await apiClient.delete(`/api/accounts/${id}/`);
}

export async function refreshAccount(id: number, options?: { signal?: AbortSignal }): Promise<Account> {
  const { data } = await apiClient.post<Account>(
    `/api/accounts/${id}/refresh/`,
    undefined,
    { timeout: 300_000, signal: options?.signal },
  );
  return data;
}

export interface BulkRefreshError {
  id: number;
  detail: string;
}

export async function refreshAccountsBulk(
  ids: number[],
  options?: { signal?: AbortSignal },
): Promise<{
  accounts: Account[];
  errors: BulkRefreshError[];
}> {
  const { data } = await apiClient.post<{ accounts: Account[]; errors: BulkRefreshError[] }>(
    "/api/accounts/bulk-refresh/",
    { ids },
    { timeout: 600_000, signal: options?.signal },
  );
  return data;
}

export async function getAccount(id: number): Promise<Account> {
  const { data } = await apiClient.get<Account>(`/api/accounts/${id}/`);
  return data;
}

export async function getAccountPosts(id: number): Promise<Post[]> {
  const { data } = await apiClient.get<Post[]>(`/api/accounts/${id}/posts/`);
  return data;
}

export async function refreshAllAccounts(downloadCsv: boolean = false): Promise<RefreshAllResult> {
  const { data } = await apiClient.post<RefreshAllResult>(
    `/api/accounts/refresh_all/${downloadCsv ? "?download_csv=1" : ""}`
  );
  return data;
}

export async function getPlatforms(): Promise<Platform[]> {
  const { data } = await apiClient.get<Platform[]>("/api/accounts/platforms/");
  return data;
}

export interface PlatformSummary {
  platform: string;
  platform_label: string;
  account_count: number;
  follower_count: number;
  like_count: number;
  view_count: number;
  post_count: number;
}

export interface Summary {
  account_count: number;
  follower_count: number;
  like_count: number;
  view_count: number;
  post_count: number;
  follower_delta: number | null;
  like_delta: number | null;
  view_delta: number | null;
  post_delta: number | null;
  by_platform: PlatformSummary[];
}

export async function getSummary(): Promise<Summary> {
  const { data } = await apiClient.get<Summary>("/api/accounts/summary/");
  return data;
}

export interface RefreshSchedule {
  enabled: boolean;
  mode: "interval" | "times";
  interval_hours: number;
  skip_recent_hours: number;
  /** Сохранять CSV после каждого завершённого автообновления (скачивание в интерфейсе). */
  auto_refresh_csv_report?: boolean;
  /** В автообновлении учитывать аккаунты скрытых платформ. */
  include_hidden_platform_accounts?: boolean;
  /** В автообновлении учитывать аккаунты скрытых профилей. */
  include_hidden_profile_accounts?: boolean;
  times: string[];
}

export interface GlobalVisibility {
  hidden_platforms: string[];
  hidden_profile_ids: number[];
}

export interface AutoRefreshStatus {
  is_running: boolean;
  source: string;
  cancel_requested?: boolean;
  total_accounts: number;
  processed_accounts: number;
  success_accounts: number;
  failed_accounts: number;
  progress_percent: number;
  current_account: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  updated_at: string;
  has_csv_report?: boolean;
  report_generated_at?: string | null;
}

export async function getSchedule(): Promise<RefreshSchedule> {
  const { data } = await apiClient.get<RefreshSchedule>("/api/accounts/schedule/");
  return data;
}

export async function getGlobalVisibility(): Promise<GlobalVisibility> {
  const { data } = await apiClient.get<GlobalVisibility>("/api/accounts/visibility/");
  return data;
}

export async function setGlobalVisibility(payload: Partial<GlobalVisibility>): Promise<GlobalVisibility> {
  const { data } = await apiClient.post<GlobalVisibility>("/api/accounts/visibility/", payload);
  return data;
}

export async function setSchedule(s: Partial<RefreshSchedule>): Promise<RefreshSchedule> {
  const { data } = await apiClient.post<RefreshSchedule>("/api/accounts/schedule/", s);
  return data;
}

export async function getAutoRefreshStatus(): Promise<AutoRefreshStatus> {
  const { data } = await apiClient.get<AutoRefreshStatus>("/api/accounts/auto-refresh-status/");
  return data;
}

export async function runAutoRefreshNow(): Promise<{ started: boolean; detail?: string }> {
  const { data } = await apiClient.post<{ started: boolean; detail?: string }>(
    "/api/accounts/auto-refresh-run-now/",
  );
  return data;
}

export async function stopAutoRefresh(): Promise<{ stopped: boolean; detail?: string }> {
  const { data } = await apiClient.post<{ stopped: boolean; detail?: string }>(
    "/api/accounts/auto-refresh-stop/",
  );
  return data;
}

/** CSV последнего автообновления (UTF-8 BOM). Ошибка — если отчёта ещё нет. */
export async function downloadAutoRefreshReport(): Promise<void> {
  const res = await apiClient.get<Blob>("/api/accounts/auto-refresh-report/", {
    responseType: "blob",
    validateStatus: () => true,
  });
  if (res.status !== 200) {
    let msg = "Не удалось скачать отчёт.";
    try {
      const t = await res.data.text();
      const j = JSON.parse(t) as { detail?: string };
      if (j.detail) msg = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  const url = window.URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `auto-refresh-report-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
  a.click();
  window.URL.revokeObjectURL(url);
}

export interface SnapshotImportResult {
  accounts_created: number;
  accounts_updated: number;
  posts_created: number;
  posts_updated: number;
  account_snapshots_upserted?: number;
  post_snapshots_upserted?: number;
  errors: Array<{ section: string; row: number; message: string }>;
}

/** Полный снимок: аккаунты + посты, UTF-8 с BOM, секции # ACCOUNTS / # POSTS. */
export async function downloadSnapshotExport(): Promise<void> {
  const { data } = await apiClient.get<Blob>("/api/accounts/export-snapshot/", { responseType: "blob" });
  const url = window.URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `dashboard-snapshot-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
  a.click();
  window.URL.revokeObjectURL(url);
}

export async function importSnapshotFile(file: File): Promise<SnapshotImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await apiClient.post<SnapshotImportResult>(
    "/api/accounts/import-snapshot/",
    fd,
    {
      // Let browser/axios set proper multipart boundary.
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 600_000,
    },
  );
  return data;
}
