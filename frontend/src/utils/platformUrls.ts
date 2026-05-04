/** Локальная часть username без ведущих @ */
function normUser(username: string): string {
  return username.replace(/^@+/, "").trim();
}

/**
 * Публичная страница профиля на площадке (для ссылок из UI).
 * Username в API обычно без @, кроме rumble (slug канала).
 */
export function externalProfileUrl(platform: string, username: string): string | null {
  const u = normUser(username);
  if (!u) return null;

  switch (platform) {
    case "tiktok":
      return `https://www.tiktok.com/@${encodeURIComponent(u)}`;
    case "instagram":
      return `https://www.instagram.com/${encodeURIComponent(u)}/`;
    case "youtube":
      if (/^UC[\w-]{10,}$/i.test(u)) {
        return `https://www.youtube.com/channel/${encodeURIComponent(u)}`;
      }
      return `https://www.youtube.com/@${encodeURIComponent(u)}`;
    case "telegram":
      return `https://t.me/${encodeURIComponent(u)}`;
    case "x":
      return `https://x.com/${encodeURIComponent(u)}`;
    case "threads":
      return `https://www.threads.net/@${encodeURIComponent(u)}`;
    case "facebook":
      if (/^\d+$/.test(u)) {
        return `https://www.facebook.com/profile.php?id=${encodeURIComponent(u)}`;
      }
      return `https://www.facebook.com/${encodeURIComponent(u)}`;
    case "rumble":
      return `https://rumble.com/c/${encodeURIComponent(u)}`;
    default:
      return null;
  }
}
