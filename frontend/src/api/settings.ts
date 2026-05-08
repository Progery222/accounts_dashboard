import { apiClient } from "./client";

export interface CookieInfo {
  host: string;
  name: string;
  expires: string | null;
  expires_ts: number | null;
}

export interface TikTokStatus {
  has_session: boolean;
  cookies: CookieInfo[];
  min_expires: string | null;
  min_expires_name: string | null;
}

export interface InstagramStatus {
  has_session: boolean;
  username: string;
  last_updated: string | null;
}

export interface TelegramStatus {
  has_session: boolean;
  profile_exists: boolean;
}

export interface XStatus {
  has_session: boolean;
}

export interface ThreadsStatus {
  has_session: boolean;
}

export interface FacebookStatus {
  has_session: boolean;
}

export interface RumbleStatus {
  has_session: boolean;
}

export interface RedditStatus {
  has_session: boolean;
}

export interface AuthStatus {
  tiktok:    TikTokStatus;
  instagram: InstagramStatus;
  telegram:  TelegramStatus;
  x:         XStatus;
  threads:   ThreadsStatus;
  facebook:  FacebookStatus;
  rumble:    RumbleStatus;
  reddit:    RedditStatus;
}

/** Платформы с сохранённой сессией в настройках (POST …/logout/). */
export type AuthPlatform = keyof AuthStatus;

export interface JobStatus {
  status: "pending" | "done" | "error";
  message: string;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const r = await apiClient.get<AuthStatus>("/api/settings/status/");
  return r.data;
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const r = await apiClient.get<JobStatus>(`/api/settings/job/${jobId}/`);
  return r.data;
}

export async function startTikTokAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/tiktok/start-auth/");
  return r.data;
}

export async function importTikTokCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/tiktok/import-cookies/", { cookies });
  return r.data;
}

export async function importInstagramCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/instagram/import-cookies/", { cookies });
  return r.data;
}

export async function importXCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/x/import-cookies/", { cookies });
  return r.data;
}

export async function importThreadsCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/threads/import-cookies/", { cookies });
  return r.data;
}

export async function startInstagramAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/instagram/start-auth/");
  return r.data;
}

export async function startTelegramAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/telegram/start-auth/");
  return r.data;
}

export async function startXAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/x/start-auth/");
  return r.data;
}

export async function startThreadsAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/threads/start-auth/");
  return r.data;
}

export async function startFacebookAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/facebook/start-auth/");
  return r.data;
}

export async function importFacebookCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/facebook/import-cookies/", { cookies });
  return r.data;
}

export async function startRumbleAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/rumble/start-auth/");
  return r.data;
}

export async function importRumbleCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/rumble/import-cookies/", { cookies });
  return r.data;
}

export async function startRedditAuth(): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/reddit/start-auth/");
  return r.data;
}

export async function importRedditCookies(cookies: string): Promise<{ job_id: string }> {
  const r = await apiClient.post<{ job_id: string }>("/api/settings/reddit/import-cookies/", { cookies });
  return r.data;
}

export async function logoutPlatform(platform: AuthPlatform): Promise<void> {
  await apiClient.post(`/api/settings/${platform}/logout/`);
}
