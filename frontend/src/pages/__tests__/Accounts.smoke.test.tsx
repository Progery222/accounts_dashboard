import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";

import Accounts from "../Accounts";

vi.mock("../../api/accounts", async () => {
  const actual = await vi.importActual<typeof import("../../api/accounts")>("../../api/accounts");
  return {
    ...actual,
    getAccounts: vi.fn().mockResolvedValue([
      {
        id: 1,
        username: "demo",
        platform: "tiktok",
        platform_label: "TikTok",
        profile_id: null,
        profile_name: null,
        profile_color: null,
        display_name: "Demo account",
        avatar_url: "",
        bio: "",
        follower_count: 100,
        like_count: 50,
        view_count: 10,
        post_count: 1,
        follower_delta: 1,
        like_delta: 1,
        view_delta: 1,
        post_delta: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]),
    getPlatforms: vi.fn().mockResolvedValue([{ value: "tiktok", label: "TikTok" }]),
    getSchedule: vi.fn().mockResolvedValue({
      enabled: false,
      mode: "interval",
      interval_hours: 6,
      times: [],
    }),
  };
});

vi.mock("../../api/profiles", () => ({
  getProfiles: vi.fn().mockResolvedValue([]),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  deleteProfile: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <Accounts />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("Accounts smoke", () => {
  it("renders page controls", async () => {
    renderPage();
    expect(await screen.findByText("Обновить всё")).toBeInTheDocument();
    expect(screen.getByText("+ Добавить")).toBeInTheDocument();
  });

  it("renders account row", async () => {
    renderPage();
    expect(await screen.findByText("Demo account")).toBeInTheDocument();
    expect(screen.getByText("@demo")).toBeInTheDocument();
  });
});
