import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  SubsEnrichResultModal,
  type EnrichMemberSummary,
  type EnrichResultPayload,
} from "./subsEnrichResultModal";

export type SubsMembersPreviewAccount = {
  id: number;
  username: string;
  display_name?: string;
  platform: string;
  dashboard_account_id: number | null;
  audience_count?: number;
};

type MemberRow = {
  id: number;
  platform: string;
  username: string;
  display_name: string;
  bio?: string;
  follower_count?: number;
  is_private: boolean;
  updated_at: string | null;
};

type AudienceSyncResp = {
  enriched_members?: EnrichMemberSummary[];
  enriched_ok_count?: number;
  enriched_weak_count?: number;
  dashboard?: {
    enriched_members?: EnrichMemberSummary[];
    enriched_ok_count?: number;
    enriched_weak_count?: number;
    followers_saved?: number;
  };
};

function parseEnrichResponse(body: unknown): {
  members: EnrichMemberSummary[];
  okCount: number;
  weakCount: number;
  savedCount: number;
} {
  if (!body || typeof body !== "object") {
    return { members: [], okCount: 0, weakCount: 0, savedCount: 0 };
  }
  const o = body as AudienceSyncResp;
  const dash = o.dashboard;
  const members = Array.isArray(o.enriched_members)
    ? o.enriched_members
    : Array.isArray(dash?.enriched_members)
      ? dash.enriched_members
      : [];
  const okCount = Number(
    o.enriched_ok_count ?? dash?.enriched_ok_count ?? members.filter((m) => m.enrich_ok !== false).length,
  );
  const weakCount = Number(
    o.enriched_weak_count ?? dash?.enriched_weak_count ?? members.filter((m) => m.enrich_ok === false).length,
  );
  const savedCount = Number(dash?.followers_saved ?? members.length);
  return { members, okCount, weakCount, savedCount };
}

function fmtNumShort(n: number | undefined): string {
  const v = Number(n ?? 0);
  if (!v) return "";
  return v.toLocaleString("ru-RU");
}

type MembersPageResp = {
  count: number;
  page: number;
  page_size: number;
  results: MemberRow[];
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type SubsMembersPreviewModalProps = {
  account: SubsMembersPreviewAccount;
  onClose: () => void;
  fetchJson: (url: string, init?: RequestInit) => Promise<unknown>;
  subsApiBase: string;
  showToast: (msg: string, isErr: boolean) => void;
  platformColor: string;
  platformLabel: string;
  bulkBusy: boolean;
  onRequestAudienceStop: () => void;
};

export function SubsMembersPreviewModal(props: SubsMembersPreviewModalProps) {
  const {
    account,
    onClose,
    fetchJson,
    subsApiBase,
    showToast,
    platformColor,
    platformLabel,
    bulkBusy,
    onRequestAudienceStop,
  } = props;

  const enrichAbortRef = useRef<AbortController | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [memberSearch, setMemberSearch] = useState("");
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [enrichAllBusy, setEnrichAllBusy] = useState(false);
  const [enrichResult, setEnrichResult] = useState<EnrichResultPayload | null>(null);
  const [enrichBefore, setEnrichBefore] = useState<Map<string, MemberRow> | null>(null);

  const loadMembers = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const pageSize = 100;
      let page = 1;
      let total = 0;
      const rows: MemberRow[] = [];
      do {
        const qs = new URLSearchParams({
          for_account: String(account.id),
          page: String(page),
          page_size: String(pageSize),
        });
        const body = (await fetchJson(`${subsApiBase}/api/subscribers/members/?${qs}`)) as MembersPageResp;
        total = body.count ?? 0;
        for (const m of body.results ?? []) {
          rows.push(m);
        }
        if (!body.results?.length || rows.length >= total) break;
        page += 1;
      } while (page <= 50);
      rows.sort((a, b) => a.username.localeCompare(b.username, "ru"));
      setMembers(rows);
    } catch (e) {
      setMembers([]);
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [account.id, fetchJson, subsApiBase]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !enrichAllBusy && refreshingId == null) onClose();
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [onClose, enrichAllBusy, refreshingId]);

  const filtered = useMemo(() => {
    const q = memberSearch.trim().toLowerCase();
    if (!q) return members;
    return members.filter((m) => {
      const u = m.username.toLowerCase();
      const d = (m.display_name || "").toLowerCase();
      return u.includes(q) || d.includes(q);
    });
  }, [members, memberSearch]);

  const stopEnrich = useCallback(() => {
    enrichAbortRef.current?.abort();
    enrichAbortRef.current = null;
    onRequestAudienceStop();
    setEnrichAllBusy(false);
    setRefreshingId(null);
    showToast("Обновление остановлено", false);
  }, [onRequestAudienceStop, showToast]);

  const enrichMember = async (m: MemberRow) => {
    if (!account.dashboard_account_id) {
      showToast("Нет связи с дашбордом", true);
      return;
    }
    enrichAbortRef.current?.abort();
    const ac = new AbortController();
    enrichAbortRef.current = ac;
    setRefreshingId(m.id);
    const beforeMap = new Map([[m.username, m]]);
    try {
      const resp = await fetchJson(`${subsApiBase}/api/subscribers/sync/account/${account.id}/audience/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audience_mode: "enrich",
          enrich_usernames: [m.username],
        }),
        signal: ac.signal,
      });
      if (ac.signal.aborted) return;
      const parsed = parseEnrichResponse(resp);
      setEnrichBefore(beforeMap);
      setEnrichResult({
        members: parsed.members,
        okCount: parsed.okCount,
        weakCount: parsed.weakCount,
        savedCount: parsed.savedCount,
      });
      await loadMembers();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      showToast(e instanceof Error ? e.message : String(e), true);
    } finally {
      if (enrichAbortRef.current === ac) enrichAbortRef.current = null;
      setRefreshingId(null);
    }
  };

  const enrichAll = async () => {
    if (!account.dashboard_account_id) {
      showToast("Нет связи с дашбордом", true);
      return;
    }
    enrichAbortRef.current?.abort();
    const ac = new AbortController();
    enrichAbortRef.current = ac;
    setEnrichAllBusy(true);
    const beforeMap = new Map(members.map((row) => [row.username, row]));
    try {
      const resp = await fetchJson(`${subsApiBase}/api/subscribers/sync/account/${account.id}/audience/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audience_mode: "enrich" }),
        signal: ac.signal,
      });
      if (ac.signal.aborted) return;
      const parsed = parseEnrichResponse(resp);
      setEnrichBefore(beforeMap);
      setEnrichResult({
        members: parsed.members,
        okCount: parsed.okCount,
        weakCount: parsed.weakCount,
        savedCount: parsed.savedCount,
      });
      await loadMembers();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      showToast(e instanceof Error ? e.message : String(e), true);
    } finally {
      if (enrichAbortRef.current === ac) enrichAbortRef.current = null;
      setEnrichAllBusy(false);
    }
  };

  const busy = bulkBusy || enrichAllBusy || refreshingId != null;

  return (
    <>
    <div
      className="subs-modal-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 92,
        background: "rgba(0,0,0,0.85)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-labelledby="subs-members-preview-title"
        className="subs-modal-panel"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 520,
          width: "100%",
          maxHeight: "min(88vh, 640px)",
          display: "flex",
          flexDirection: "column",
          borderRadius: 16,
          border: "1px solid var(--line-strong)",
          background: "var(--panel)",
          padding: 20,
          boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", letterSpacing: "0.18em", margin: "0 0 6px" }}>
              ПОДПИСЧИКИ В БД
            </p>
            <h3 id="subs-members-preview-title" style={{ margin: 0, fontSize: 17, color: "var(--ink)" }}>
              @{account.username}
            </h3>
            <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--ink-mute)" }}>
              <span className="subs-dot" style={{ background: platformColor, verticalAlign: "middle", marginRight: 6 }} />
              {platformLabel}
              {account.display_name ? ` · ${account.display_name}` : ""}
              <span className="tnum"> · {members.length} в БД</span>
            </p>
          </div>
          <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={onClose} disabled={busy} aria-label="Закрыть">
            ✕
          </button>
        </div>

        <div className="subs-field-wrap" style={{ marginBottom: 12 }}>
          <input
            value={memberSearch}
            onChange={(e) => setMemberSearch(e.target.value)}
            placeholder="Поиск по @нику или имени…"
            className="subs-field"
            disabled={loading}
          />
          <span className="subs-field-icon">⌕</span>
        </div>

        <div
          className="subs-bulk-pick-scroll"
          style={{
            flex: 1,
            minHeight: 120,
            overflow: "auto",
            border: "1px solid var(--line)",
            borderRadius: 12,
            padding: "6px 8px",
            marginBottom: 14,
          }}
        >
          {loading ? (
            <p className="subs-muted" style={{ margin: 10 }}>Загрузка…</p>
          ) : loadErr ? (
            <p style={{ margin: 10, color: "var(--danger)", fontSize: 13 }}>{loadErr}</p>
          ) : filtered.length === 0 ? (
            <p className="subs-muted" style={{ margin: 10 }}>Нет подписчиков по фильтру.</p>
          ) : (
            filtered.map((m) => {
              const rowBusy = refreshingId === m.id;
              return (
                <div key={m.id} className="subs-member-preview-row">
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 600, color: "var(--ink)" }}>@{m.username}</span>
                    {m.display_name ? (
                      <span style={{ display: "block", fontSize: 12, color: "var(--ink-mute)", marginTop: 2 }}>
                        {m.display_name}
                      </span>
                    ) : null}
                    <span className="tnum" style={{ display: "block", fontSize: 11, color: "var(--ink-dim)", marginTop: 4 }}>
                      {fmtNumShort(m.follower_count) ? (
                        <>
                          Подписчики: {fmtNumShort(m.follower_count)}
                          {" · "}
                        </>
                      ) : null}
                      Обновлён: {fmtDate(m.updated_at)}
                      {m.is_private ? " · закрытый" : ""}
                    </span>
                    {m.bio ? (
                      <span style={{ display: "block", fontSize: 11, color: "var(--ink-mute)", marginTop: 2, lineHeight: 1.35 }}>
                        {m.bio.length > 80 ? `${m.bio.slice(0, 80)}…` : m.bio}
                      </span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="subs-btn subs-btn--sm subs-btn--muted"
                    disabled={busy}
                    onClick={() => void enrichMember(m)}
                  >
                    {rowBusy ? "…" : "Обновить"}
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="subs-modal-footer">
          <div style={{ fontSize: 12, color: "var(--ink-mute)", lineHeight: 1.45, minWidth: 0 }}>
            Показано <strong className="tnum">{filtered.length}</strong> из <strong className="tnum">{members.length}</strong>
          </div>
          <div className="subs-modal-footer-actions">
            <button type="button" className="subs-btn subs-btn--muted subs-btn--sm" onClick={onClose} disabled={enrichAllBusy}>
              Закрыть
            </button>
            {enrichAllBusy ? (
              <button
                type="button"
                className="subs-btn subs-btn--sm subs-btn--danger-text"
                style={{ padding: "10px 16px", fontSize: 13 }}
                onClick={stopEnrich}
              >
                Остановить
              </button>
            ) : (
              <button
                type="button"
                className="subs-btn-emphasis"
                style={{ padding: "10px 16px", fontSize: 13 }}
                disabled={busy || loading || members.length === 0 || !account.dashboard_account_id}
                onClick={() => void enrichAll()}
              >
                Обновить всех
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
    {enrichResult ? (
      <SubsEnrichResultModal
        result={enrichResult}
        beforeByUsername={enrichBefore ?? undefined}
        onClose={() => {
          setEnrichResult(null);
          setEnrichBefore(null);
        }}
      />
    ) : null}
    </>
  );
}
