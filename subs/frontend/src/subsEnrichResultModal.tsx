export type EnrichMemberSummary = {
  username: string;
  display_name?: string;
  follower_count?: number;
  following_count?: number;
  like_count?: number;
  bio?: string;
  is_private?: boolean;
  enrich_ok?: boolean;
  enrich_note?: string;
};

export type EnrichResultPayload = {
  members: EnrichMemberSummary[];
  okCount: number;
  weakCount: number;
  savedCount?: number;
};

function fmtNum(n: number | undefined): string {
  const v = Number(n ?? 0);
  if (!v) return "—";
  return v.toLocaleString("ru-RU");
}

function fmtDelta(before: number | undefined, after: number | undefined): string | null {
  const b = Number(before ?? 0);
  const a = Number(after ?? 0);
  if (a === b) return null;
  const d = a - b;
  const sign = d > 0 ? "+" : "";
  return `${sign}${d.toLocaleString("ru-RU")}`;
}

type SubsEnrichResultModalProps = {
  result: EnrichResultPayload;
  onClose: () => void;
  beforeByUsername?: Map<string, { follower_count?: number; display_name?: string; bio?: string }>;
};

export function SubsEnrichResultModal(props: SubsEnrichResultModalProps) {
  const { result, onClose, beforeByUsername } = props;
  const { members, okCount, weakCount, savedCount } = result;

  return (
    <div
      className="subs-modal-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 94,
        background: "rgba(0,0,0,0.88)",
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-labelledby="subs-enrich-result-title"
        className="subs-modal-panel subs-modal-panel--wide"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 560,
          width: "100%",
          maxHeight: "min(88vh, 680px)",
          display: "flex",
          flexDirection: "column",
          borderRadius: 16,
          border: "1px solid var(--line-strong)",
          background: "var(--panel)",
          padding: 20,
          boxShadow: "0 24px 56px rgba(0,0,0,0.65)",
        }}
      >
        <div className="subs-modal-title-row" style={{ marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", letterSpacing: "0.18em", margin: "0 0 6px" }}>
              РЕЗУЛЬТАТ ОБНОВЛЕНИЯ
            </p>
            <h3 id="subs-enrich-result-title" style={{ margin: 0, fontSize: 17, color: "var(--ink)" }}>
              Полученные данные
            </h3>
            <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--ink-mute)", lineHeight: 1.45 }}>
              Сохранено в БД: <strong className="tnum">{savedCount ?? members.length}</strong>
              {" · "}
              с данными: <strong className="tnum" style={{ color: "#4ade80" }}>{okCount}</strong>
              {" · "}
              слабый ответ: <strong className="tnum" style={{ color: weakCount ? "#fbbf24" : "inherit" }}>{weakCount}</strong>
            </p>
          </div>
          <button type="button" className="subs-btn subs-btn--sm subs-btn--muted" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
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
          {members.length === 0 ? (
            <p className="subs-muted" style={{ margin: 10 }}>
              Нет детализации по подписчикам. Проверьте логи worker на сервере.
            </p>
          ) : (
            members.map((m) => {
              const before = beforeByUsername?.get(m.username);
              const delta = fmtDelta(before?.follower_count, m.follower_count);
              const ok = m.enrich_ok !== false;
              return (
                <div
                  key={m.username}
                  className="subs-member-preview-row"
                  style={{
                    borderLeft: `3px solid ${ok ? "rgba(74,222,128,0.55)" : "rgba(251,191,36,0.55)"}`,
                    paddingLeft: 10,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 600, color: "var(--ink)" }}>@{m.username}</span>
                    {m.display_name ? (
                      <span style={{ display: "block", fontSize: 12, color: "var(--ink-mute)", marginTop: 2 }}>
                        {m.display_name}
                      </span>
                    ) : null}
                    <span className="tnum" style={{ display: "block", fontSize: 11, color: "var(--ink-dim)", marginTop: 4 }}>
                      Подписчики: {fmtNum(m.follower_count)}
                      {delta ? (
                        <span style={{ color: "var(--ink-mute)", marginLeft: 6 }}>({delta})</span>
                      ) : null}
                      {" · "}
                      подписки: {fmtNum(m.following_count)}
                      {m.is_private ? " · закрытый" : ""}
                    </span>
                    {m.bio ? (
                      <span style={{ display: "block", fontSize: 11, color: "var(--ink-mute)", marginTop: 4, lineHeight: 1.35 }}>
                        {m.bio}
                      </span>
                    ) : null}
                    {!ok && m.enrich_note ? (
                      <span style={{ display: "block", fontSize: 11, color: "#fbbf24", marginTop: 4 }}>
                        {m.enrich_note}
                      </span>
                    ) : null}
                  </div>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: "3px 8px",
                      borderRadius: 6,
                      border: "1px solid var(--line)",
                      background: ok ? "rgba(74,222,128,0.1)" : "rgba(251,191,36,0.1)",
                      color: "var(--ink)",
                      flexShrink: 0,
                      alignSelf: "flex-start",
                    }}
                  >
                    {ok ? "OK" : "мало данных"}
                  </span>
                </div>
              );
            })
          )}
        </div>

        <div className="subs-modal-footer">
          <p style={{ fontSize: 12, color: "var(--ink-mute)", margin: 0, lineHeight: 1.45, flex: 1 }}>
            Данные записаны в дашборд и синхронизированы в subs. «Мало данных» — страница открылась, но имя, био или счётчики не распознаны.
          </p>
          <div className="subs-modal-footer-actions">
            <button type="button" className="subs-btn-emphasis subs-btn--sm" onClick={onClose}>
              Понятно
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
