import { apiClient } from "./client";

export interface AnalyticsAccount {
  id: number;
  username: string;
  platform: string;
  platform_label: string;
  display_name: string;
  avatar_url: string;
}

export interface AnalyticsPost {
  id: number;
  external_id: string;
  description: string;
  hashtags: string[];
  thumbnail_url: string;
  post_url: string;
  posted_at: string | null;
  account: AnalyticsAccount;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  engagement_rate: number;
  view_delta: number;
  like_delta: number;
}

export interface TopPostsResult {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  items: AnalyticsPost[];
}

export interface PlatformStat {
  platform: string;
  platform_label: string;
  post_count: number;
  avg_views: number;
  avg_likes: number;
  avg_er: number;
}

export interface HashtagStat {
  tag: string;
  count: number;
  avg_views: number;
  avg_likes: number;
  avg_er: number;
}

export interface HourStat {
  hour: number;
  post_count: number;
  avg_views: number;
  avg_er: number;
}

export interface WeekdayStat {
  weekday: number;
  weekday_label: string;
  post_count: number;
  avg_views: number;
  avg_er: number;
}

export interface InsightsResult {
  platform_comparison: PlatformStat[];
  top_hashtags: HashtagStat[];
  best_hours: HourStat[];
  best_weekdays: WeekdayStat[];
}

export type Period = "1d" | "7d" | "30d" | "all";
export type SortBy = "views" | "likes" | "comments" | "shares" | "er" | "view_delta" | "like_delta";

export interface TopPostsParams {
  period?: Period;
  sort_by?: SortBy;
  platform?: string;
  account_id?: number;
  min_views?: number;
  hashtag?: string;
  page?: number;
  page_size?: number;
}

export async function getTopPosts(params: TopPostsParams = {}): Promise<TopPostsResult> {
  const { data } = await apiClient.get<TopPostsResult>("/api/accounts/analytics/top-posts/", { params });
  return data;
}

export async function getInsights(params: Omit<TopPostsParams, "sort_by" | "page" | "page_size"> = {}): Promise<InsightsResult> {
  const { data } = await apiClient.get<InsightsResult>("/api/accounts/analytics/insights/", { params });
  return data;
}
