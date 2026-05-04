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
  times: string[];
}

export async function getSchedule(): Promise<RefreshSchedule> {
  const { data } = await apiClient.get<RefreshSchedule>("/api/accounts/schedule/");
  return data;
}

export async function setSchedule(s: Partial<RefreshSchedule>): Promise<RefreshSchedule> {
  const { data } = await apiClient.post<RefreshSchedule>("/api/accounts/schedule/", s);
  return data;
}

export interface SnapshotImportResult {
  accounts_created: number;
  accounts_updated: number;
  posts_created: number;
  posts_updated: number;
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
  const { data } = await apiClient.post<SnapshotImportResult>("/api/accounts/import-snapshot/", fd);
  return data;
}
