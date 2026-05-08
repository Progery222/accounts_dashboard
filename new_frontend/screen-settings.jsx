// Settings (auth) screen — atomic-themed redesign of "Настройки авторизации".

function SettingsScreen({ tweaks, onBack }) {
  const accent = tweaks.accent || '#6aa9ff';
  const platforms = [
    { id: 'tiktok',    name: 'TikTok',    state: 'active', expires: '5 дн.', meta: 'perf_feed_cache', warn: true,  account: null },
    { id: 'instagram', name: 'Instagram', state: 'active', updated: '2026-05-04 08:47 UTC', warn: false, account: '@asti22297' },
    { id: 'telegram',  name: 'Telegram',  state: 'detected', meta: 'Данные хранятся в браузерном профиле', warn: false, account: null },
    { id: 'youtube',   name: 'YouTube',   state: 'active', updated: '2026-05-06 14:12 UTC', warn: false, account: '@phil.studio' },
    { id: 'twitter',   name: 'X (Twitter)', state: 'expired', warn: true, account: null },
    { id: 'threads',   name: 'Threads',   state: 'active', updated: '2026-05-05 10:24 UTC', warn: false, account: '@asti22297' },
  ];
  return (
    <div style={{ minHeight: '100vh' }} data-screen-label="Settings">
      <TopBar accent={accent} />
      <main style={{ maxWidth: 1100, margin: '0 auto', padding: '28px 36px 80px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
          <button onClick={onBack} style={{ padding: '8px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--line)', color: 'var(--ink)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>← Назад</button>
          <div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.22em' }}>SECURITY · SESSIONS</div>
            <div style={{ fontSize: 26, fontWeight: 600, marginTop: 2, letterSpacing: '-0.01em' }}>Настройки авторизации</div>
          </div>
        </div>
        <p style={{ color: 'var(--ink-dim)', fontSize: 14, lineHeight: 1.6, marginBottom: 24, maxWidth: 720 }}>
          Для сбора данных приложение использует авторизованные сессии в браузере. Нажмите кнопку — откроется окно, войдите в аккаунт, и данные будут обновляться автоматически.
        </p>

        {/* Summary tile */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, marginBottom: 28 }}>
          <SummaryTile label="АКТИВНЫХ" value="4" color="#4ade80" />
          <SummaryTile label="ИСТЕКАЮТ" value="1" color="#f59e0b" warn />
          <SummaryTile label="ИСТЕКЛО" value="1" color="#ef4444" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {platforms.map(p => <SessionCard key={p.id} p={p} accent={accent} />)}
        </div>
      </main>
    </div>
  );
}

function SummaryTile({ label, value, color, warn }) {
  return (
    <div style={{ padding: 20, borderRadius: 14, border: '1px solid var(--line)', background: 'rgba(255,255,255,0.015)', position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: 0, left: 0, width: 4, bottom: 0, background: color, opacity: 0.6 }} />
      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.22em' }}>{label}</div>
      <div className="tnum" style={{ fontSize: 40, fontWeight: 700, color, marginTop: 4, letterSpacing: '-0.02em' }}>{value}</div>
    </div>
  );
}

function SessionCard({ p, accent }) {
  const meta = PLATFORM_META[p.id];
  const stateColor = p.state === 'active' || p.state === 'detected' ? '#4ade80' : p.state === 'expired' ? '#ef4444' : '#f59e0b';
  return (
    <div style={{ padding: 22, borderRadius: 16, border: '1px solid var(--line)', background: 'rgba(255,255,255,0.015)', position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, ${meta?.color || accent}, transparent)`, opacity: 0.5 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,0.04)',
            border: `1px solid ${meta?.color}40`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            color: meta?.color, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace',
          }}>{p.name.charAt(0)}</span>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{p.name}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 7, height: 7, borderRadius: 999, background: stateColor, boxShadow: `0 0 8px ${stateColor}` }} />
          <span className="mono" style={{ fontSize: 11, color: stateColor, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
            {p.state === 'active' ? 'Авторизован' : p.state === 'detected' ? 'Обнаружено' : 'Истекло'}
          </span>
        </div>
      </div>

      {p.account && <div className="mono" style={{ fontSize: 13, color: 'var(--ink-dim)', marginBottom: 4 }}>{p.account}</div>}
      {p.updated && <div className="mono" style={{ fontSize: 12, color: 'var(--ink-mute)' }}>Обновлено: {p.updated}</div>}
      {p.expires && (
        <div style={{ marginTop: 10, padding: '6px 10px', display: 'inline-flex', gap: 8, alignItems: 'center', borderRadius: 8, background: '#ef444415', border: '1px solid #ef444433' }}>
          <span className="mono" style={{ fontSize: 11, color: '#ef4444' }}>● {p.expires}</span>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)' }}>{p.meta}</span>
        </div>
      )}
      {p.meta && !p.expires && <div className="mono" style={{ fontSize: 12, color: 'var(--ink-mute)', marginTop: 4 }}>{p.meta}</div>}

      {p.warn && p.state === 'active' && (
        <div style={{ marginTop: 14, padding: '10px 12px', borderRadius: 10, background: '#f59e0b15', border: '1px solid #f59e0b40', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <span style={{ color: '#f59e0b' }}>⚠</span>
          <span style={{ fontSize: 12, color: '#fbbf24' }}>Cookies скоро истекут — обновите авторизацию.</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 16, alignItems: 'center' }}>
        <button style={{ padding: '8px 14px', borderRadius: 10, background: '#fff', color: '#000', border: 'none', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>Обновить авторизацию</button>
        <button style={{ padding: '8px 14px', borderRadius: 10, background: 'transparent', border: '1px solid var(--line)', color: 'var(--ink-dim)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Завершить сессию</button>
      </div>
    </div>
  );
}

Object.assign(window, { SettingsScreen });
