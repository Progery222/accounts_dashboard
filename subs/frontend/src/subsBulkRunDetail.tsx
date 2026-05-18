/** Оверлей «очередь и слоты» для массового сбора подписчиков в subs. */

export type SubsBulkRunItemStatus =
  | "queued"
  | "running"
  | "done"
  | "skipped"
  | "error"
  | "cancelled";

export type SubsBulkRunItem = {
  account_id: number;
  platform: string;
  username: string;
  status: SubsBulkRunItemStatus;
  detail?: string;
  worker?: number | null;
};

export type SubsBulkRunDetail = {
  items: SubsBulkRunItem[];
  worker_count: number;
};

const STATUS_RU: Record<SubsBulkRunItemStatus, string> = {
  queued: "В очереди",
  running: "Съём",
  done: "Готово",
  skipped: "Пропущен",
  error: "Ошибка",
  cancelled: "Отменён",
};

const PLATFORM_DOT: Record<string, string> = {
  tiktok: "#ff2d55",
  instagram: "#ec4899",
  x: "#e7e9ea",
  threads: "#a8a8a8",
  facebook: "#0866ff",
};

function RunSection(props: { title: string; list: SubsBulkRunItem[]; emptyHint?: string }) {
  const { title, list, emptyHint } = props;
  return (
    <div style={{ marginBottom: 16 }}>
      <p className="mono" style={{ fontSize: 11, color: "var(--ink-mute)", letterSpacing: "0.12em", margin: "0 0 8px" }}>
        {title} · {list.length}
      </p>
      {list.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--ink-mute)", margin: 0 }}>{emptyHint || "—"}</p>
      ) : (
        <div
          style={{
            maxHeight: 160,
            overflowY: "auto",
            borderRadius: 10,
            border: "1px solid var(--line)",
            background: "rgba(0,0,0,0.2)",
          }}
        >
          {list.map((it) => (
            <div
              key={it.account_id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                padding: "8px 10px",
                borderBottom: "1px solid rgba(255,255,255,0.06)",
              }}
            >

              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 999,
                  marginTop: 5,
                  flexShrink: 0,
                  background: PLATFORM_DOT[it.platform] || "#9ca3af",
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500, margin: 0 }}>
                  @{it.username}{" "}
                  <span style={{ color: "var(--ink-mute)", fontWeight: 400 }}>· {it.platform}</span>
                </p>
                {it.detail ? (
                  <p style={{ fontSize: 11, color: "var(--ink-mute)", margin: "4px 0 0", lineHeight: 1.35 }}>{it.detail}</p>
                ) : null}
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <span
                  style={{
                    display: "inline-block",
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "3px 8px",
                    borderRadius: 6,
                    border: "1px solid var(--line)",
                    background:
                      it.status === "running"
                        ? "rgba(56,189,248,0.12)"
                        : it.status === "done"
                          ? "rgba(74,222,128,0.12)"
                          : it.status === "skipped"
                            ? "rgba(255,255,255,0.06)"
                            : "rgba(255,255,255,0.04)",
                    color: "var(--ink)",
                  }}
                >
                  {STATUS_RU[it.status] || it.status}
                </span>
                {it.worker != null && it.status === "running" ? (
                  <p className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", margin: "4px 0 0" }}>
                    слот {Number(it.worker) + 1}
                  </p>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type SubsBulkRunDetailOverlayProps = {
  detail: SubsBulkRunDetail | null;
  onClose: () => void;
};

export function SubsBulkRunDetailOverlay({ detail, onClose }: SubsBulkRunDetailOverlayProps) {
  const items = detail?.items ?? [];
  const wc = detail?.worker_count ?? 1;
  const pick = (s: SubsBulkRunItemStatus) => items.filter((it) => it.status === s);
  const buckets = {
    running: pick("running"),
    queued: pick("queued"),
    done: pick("done"),
    skipped: pick("skipped"),
    error: pick("error"),
    cancelled: pick("cancelled"),
  };
  const runningUser = buckets.running[0]?.username;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 90,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.72)",
        padding: 16,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal
        aria-labelledby="subs-bulk-run-detail-title"
        style={{
          width: "100%",
          maxWidth: 520,
          maxHeight: "min(88vh, 620px)",
          overflowY: "auto",
          borderRadius: 16,
          border: "1px solid var(--line)",
          background: "rgba(18,20,28,0.98)",
          padding: 20,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div>
            <p className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", letterSpacing: "0.2em", margin: "0 0 6px" }}>
              СБОР ПОДПИСЧИКОВ
            </p>
            <h3 id="subs-bulk-run-detail-title" style={{ margin: 0, fontSize: 17, fontWeight: 600, color: "#fff" }}>
              Очередь и слоты
            </h3>
            <p style={{ fontSize: 12, color: "var(--ink-mute)", marginTop: 8, lineHeight: 1.45, marginBottom: 0 }}>
              До {wc} аккаунтов параллельно; на каждой площадке (TikTok, Instagram, X, Threads, Facebook) — не
              больше одного съёма одновременно.
              {runningUser ? ` Сейчас: @${runningUser}${buckets.running.length > 1 ? ` и ещё ${buckets.running.length - 1}` : ""}.` : ""}
            </p>
            <p className="mono" style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 6 }}>
              Параллельных потоков: {wc}
            </p>
          </div>
          <button type="button" onClick={onClose} className="subs-btn subs-btn--sm subs-btn--muted" style={{ flexShrink: 0 }}>
            ✕
          </button>
        </div>
        {items.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--ink-mute)" }}>Очередь ещё не сформирована.</p>
        ) : (
          <>
            <RunSection title="Сейчас" list={buckets.running} emptyHint="Никто" />
            <RunSection title="В очереди" list={buckets.queued} emptyHint="Пусто" />
            <RunSection title="Готово" list={buckets.done} emptyHint="—" />
            <RunSection title="Пропущены" list={buckets.skipped} emptyHint="—" />
            <RunSection title="Ошибки" list={buckets.error} emptyHint="—" />
            <RunSection title="Отменены" list={buckets.cancelled} emptyHint="—" />
          </>
        )}
        <button type="button" className="subs-btn subs-btn--muted" style={{ width: "100%", marginTop: 12 }} onClick={onClose}>
          Закрыть
        </button>
      </div>
    </div>
  );
}
