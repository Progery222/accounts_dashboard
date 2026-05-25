import { AccountStatsEmbed } from "../../components/AccountStatsEmbed";
import styles from "./AccountStatsPage.module.css";

export function AccountStatsPage() {
  return (
    <div className={styles.root} data-account-stats-page>
      <div className={styles.header}>
        <h1 className={styles.title}>Аналитика аккаунтов</h1>
      </div>
      <AccountStatsEmbed />
    </div>
  );
}
