import type { MetricsHistoryPoint, MetricsHistoryResponse } from "@atome/shared";
import { Injectable } from "@nestjs/common";
import { Prisma } from "@prisma/client";
import { PrismaService } from "../prisma/prisma.service";

const PERIODS: Record<string, number> = {
  "7d": 7 * 86_400_000,
  "14d": 14 * 86_400_000,
  "30d": 30 * 86_400_000,
};

type RawRow = { ts: Date; videos: bigint; jobs_completed: bigint };

@Injectable()
export class MetricsService {
  constructor(private readonly prisma: PrismaService) {}

  async getHistory(period = "30d", resolution = "1h"): Promise<MetricsHistoryResponse> {
    const periodMs = PERIODS[period] ?? PERIODS["30d"];
    const since = new Date(Date.now() - periodMs);

    const bucket = resolution === "1d" ? "day" : "hour";
    // Inlined DATE_TRUNC unit: bound params in SELECT vs GROUP BY break PG GROUP BY rules.
    const trunc = Prisma.raw(`'${bucket}'`);

    const rows = await this.prisma.$queryRaw<RawRow[]>`
      SELECT
        DATE_TRUNC(${trunc}, "createdAt") AS ts,
        SUM("videosCount")               AS videos,
        COUNT(*)                         AS jobs_completed
      FROM "GenerationJobLog"
      WHERE status = 'done'
        AND "createdAt" >= ${since}
      GROUP BY 1
      ORDER BY 1 ASC
    `;

    const points: MetricsHistoryPoint[] = rows.map((r) => ({
      ts: new Date(r.ts).getTime(),
      videos: Number(r.videos),
      jobs_completed: Number(r.jobs_completed),
      revenue: 0,
      cost: 0,
      accounts_active: 0,
    }));

    return { period, resolution, points };
  }
}
