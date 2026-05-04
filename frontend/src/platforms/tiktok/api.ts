import { apiClient } from "../../api/client";
import type { TikTokProfile } from "./types";

export async function fetchTikTokProfile(username: string): Promise<TikTokProfile> {
  const { data } = await apiClient.get<TikTokProfile>(`/api/tiktok/${username}/`);
  return data;
}
