/** Параллельный массовый съём в subs: до 6 потоков, не больше 1 активного аккаунта на платформу. */

export const SUBS_BULK_WORKER_COUNT = 6;

/** Как в refresh_all дашборда: по одному Playwright-слоту на площадку subs. */
export const SUBS_AUDIENCE_PLATFORM_LIMITS: Record<string, number> = {
  tiktok: 1,
  instagram: 1,
  x: 1,
  threads: 1,
  facebook: 1,
};

export function interleaveAccountsByPlatform<T>(items: T[], getPlatform: (item: T) => string): T[] {
  const buckets = new Map<string, T[]>();
  const order: string[] = [];
  for (const item of items) {
    const p = getPlatform(item);
    if (!buckets.has(p)) {
      buckets.set(p, []);
      order.push(p);
    }
    buckets.get(p)!.push(item);
  }
  const out: T[] = [];
  while (true) {
    let pushed = false;
    for (const p of order) {
      const arr = buckets.get(p);
      if (arr?.length) {
        out.push(arr.shift()!);
        pushed = true;
      }
    }
    if (!pushed) break;
  }
  return out;
}

function randomPauseMs(minMs: number, maxMs: number): number {
  return Math.round(minMs + Math.random() * (maxMs - minMs));
}

type ClaimQueueState<T> = {
  items: T[];
  completed: Set<number>;
  claimed: Set<number>;
  platformActive: Map<string, number>;
  platformLimits: Record<string, number>;
  platformCooldownUntil: Map<string, number>;
};

function normalizePlatformKey(platform: string): string {
  return String(platform || "")
    .trim()
    .toLowerCase();
}

function platformLimit(limits: Record<string, number>, platform: string): number {
  const key = normalizePlatformKey(platform);
  return Math.max(1, limits[key] ?? 1);
}

function tryClaimNext<T>(
  state: ClaimQueueState<T>,
  getPlatform: (item: T) => string,
): { index: number; item: T } | null {
  const now = Date.now();
  for (let idx = 0; idx < state.items.length; idx += 1) {
    if (state.completed.has(idx) || state.claimed.has(idx)) continue;
    const platform = normalizePlatformKey(getPlatform(state.items[idx]));
    if ((state.platformCooldownUntil.get(platform) ?? 0) > now) continue;
    const active = state.platformActive.get(platform) ?? 0;
    if (active >= platformLimit(state.platformLimits, platform)) continue;
    state.claimed.add(idx);
    state.platformActive.set(platform, active + 1);
    return { index: idx, item: state.items[idx] };
  }
  return null;
}

function releaseClaim<T>(state: ClaimQueueState<T>, index: number, platform: string): void {
  state.claimed.delete(index);
  const active = (state.platformActive.get(platform) ?? 1) - 1;
  if (active <= 0) state.platformActive.delete(platform);
  else state.platformActive.set(platform, active);
}

function finishClaim<T>(state: ClaimQueueState<T>, index: number, platform: string): void {
  state.claimed.delete(index);
  state.completed.add(index);
  const active = (state.platformActive.get(platform) ?? 1) - 1;
  if (active <= 0) state.platformActive.delete(platform);
  else state.platformActive.set(platform, active);
}

/** Сколько параллельных HTTP-слотов имеет смысл при данной очереди (по числу площадок). */
export function subsBulkEffectiveWorkerCount<T>(
  accounts: T[],
  getPlatform: (item: T) => string,
  workerCount: number = SUBS_BULK_WORKER_COUNT,
): number {
  if (!accounts.length) return 0;
  const platforms = new Set(accounts.map((a) => normalizePlatformKey(getPlatform(a))));
  return Math.max(1, Math.min(workerCount, accounts.length, platforms.size, SUBS_BULK_WORKER_COUNT));
}

export type SubsBulkParallelOptions<T> = {
  accounts: T[];
  workerCount?: number;
  platformLimits?: Record<string, number>;
  getPlatform: (item: T) => string;
  shouldStop: () => boolean;
  /** Пауза после аккаунта той же площадки (мс), по умолчанию 5–9 с. */
  pauseAfterAccountMs?: { min: number; max: number };
  onClaim?: (item: T, workerSlot: number) => void;
  onRelease?: (item: T, workerSlot: number) => void;
  processAccount: (item: T, workerSlot: number) => Promise<void>;
};

/** Запускает до `workerCount` параллельных воркеров с лимитом по платформе. */
export async function runSubsBulkParallelPool<T>(options: SubsBulkParallelOptions<T>): Promise<void> {
  const {
    accounts,
    workerCount = SUBS_BULK_WORKER_COUNT,
    platformLimits = SUBS_AUDIENCE_PLATFORM_LIMITS,
    getPlatform,
    shouldStop,
    pauseAfterAccountMs = { min: 5000, max: 9000 },
    onClaim,
    onRelease,
    processAccount,
  } = options;

  if (!accounts.length) return;

  const state: ClaimQueueState<T> = {
    items: accounts,
    completed: new Set(),
    claimed: new Set(),
    platformActive: new Map(),
    platformLimits,
    platformCooldownUntil: new Map(),
  };

  const slots = subsBulkEffectiveWorkerCount(accounts, getPlatform, workerCount);

  const workerLoop = async (workerSlot: number): Promise<void> => {
    while (!shouldStop()) {
      let claimed: { index: number; item: T } | null = null;
      // Ждём слот или кулдаун платформы
      while (!shouldStop()) {
        claimed = tryClaimNext(state, getPlatform);
        if (claimed) break;
        if (state.completed.size >= state.items.length) return;
        await new Promise((r) => setTimeout(r, 200));
      }
      if (shouldStop() || !claimed) {
        if (claimed) releaseClaim(state, claimed.index, getPlatform(claimed.item));
        return;
      }
      const { index, item } = claimed;
      const platform = normalizePlatformKey(getPlatform(item));
      onClaim?.(item, workerSlot);
      try {
        await processAccount(item, workerSlot);
      } finally {
        onRelease?.(item, workerSlot);
        finishClaim(state, index, platform);
        if (!shouldStop() && state.completed.size < state.items.length) {
          state.platformCooldownUntil.set(platform, Date.now() + randomPauseMs(pauseAfterAccountMs.min, pauseAfterAccountMs.max));
        }
      }
    }
    // Остановка: вернуть незавершённые claim
    for (const idx of [...state.claimed]) {
      releaseClaim(state, idx, normalizePlatformKey(getPlatform(state.items[idx])));
    }
  };

  await Promise.all(Array.from({ length: slots }, (_, i) => workerLoop(i)));
}
