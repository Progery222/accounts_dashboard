import styles from "./AccountStatsEmbed.module.css";

/** Путь на том же origin, что Atome Studio (прокси nginx → dashboard). */
const EMBED_PATH = (import.meta.env.VITE_ACCOUNTS_STATS_EMBED_PATH as string | undefined)?.replace(/\/$/, "") || "/accounts-stats";

export function AccountStatsEmbed() {
  /** Полное приложение AccountsStats (нижняя навигация), старт с экрана «Аналитика». */
  const src = `${EMBED_PATH}/?embed=1&route=analytics`;

  return (
    <div className={styles.wrap}>
      <iframe
        className={styles.frame}
        src={src}
        title="Аналитика аккаунтов AccountsStats"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
