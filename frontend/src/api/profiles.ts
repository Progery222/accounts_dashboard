import { apiClient } from "./client";

export interface Profile {
  id: number;
  name: string;
  description: string;
  color: string;
  avatar_url: string;
  is_hidden?: boolean;
  account_count: number;
  created_at: string;
  updated_at: string;
}

export type ProfileInput = Pick<Profile, "name" | "description" | "color" | "avatar_url" | "is_hidden">;

export async function getProfiles(opts?: { includeHidden?: boolean }): Promise<Profile[]> {
  const { data } = await apiClient.get<Profile[]>("/api/accounts/profiles/", {
    params: {
      include_hidden_profiles: opts?.includeHidden ? "1" : undefined,
    },
  });
  return data;
}

export async function createProfile(input: ProfileInput): Promise<Profile> {
  const { data } = await apiClient.post<Profile>("/api/accounts/profiles/", input);
  return data;
}

export async function updateProfile(id: number, input: Partial<ProfileInput>): Promise<Profile> {
  const { data } = await apiClient.patch<Profile>(`/api/accounts/profiles/${id}/`, input);
  return data;
}

export async function deleteProfile(id: number, deleteAccounts = false): Promise<void> {
  await apiClient.delete(`/api/accounts/profiles/${id}/`, {
    params: { delete_accounts: deleteAccounts ? "true" : undefined },
  });
}
