// Analytics screen — atomic-themed redesign of "Аналитика" tab.

const { useState: useStateAn } = React;

function AnalyticsScreen({ tweaks }) {
  const accent = tweaks.accent || '#6aa9ff';
  const [period, setPeriod] = useStateAn('24h');
  const [platform, setPlatform] = useStateAn('all');

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }} data-screen-label="Analytics">
      <TopBar accent={accent} />
      <main style={{ flex: 1, padding: '28px 36px 60px', maxWidth: 1600, width: '100%', margin: '0 auto' }}>
        {/* Hero band */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr 1fr 1fr', gap: 14, marginBottom: 24 }}>
          <div style={{ borderRadius: 16, border: '1px solid var(--line)', background: 'rgba(255,255,255,0.015)', padding: 24, position: 'relative', overflow: 'hidden' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <div style={{ fontSize: 13, color: 'var(--ink-dim)', fontWeight: 500, letterSpacing: 0 }}>Engagement</div>
              <div className="mono tnum" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.16em' }}>24H</div>
            </div>
            <div className="tnum" style={{ fontSize: 64, fontWeight: 700, lineHeight: 1, marginTop: 8, letterSpacing: '-0.02em' }}>{fmt(TOTAL.views.delta + TOTAL.likes.delta)}</div>
            <div className="mono tnum" style={{ marginTop: 4, fontSize: 14, color: '#4ade80' }}>▲ +5.7% vs prev. day</div>
            <div style={{ marginTop: 12, height: 60 }}><Sparkline data={TREND_24H} color={accent} width={500} height={60} /></div>
          </div>
          {[
            { l: 'Топ постов', v: '1067', d: '+87 / 24h', c: '#ec4899', spark: TREND_24H.map(v => v * 0.4) },
            { l: 'Средний ER', v: '2.4%', d: '▲ 0.3%', c: '#f59e0b', spark: TREND_24H.map(v => v * 0.6 + 50) },
            { l: 'Вирусность', v: 'HIGH', d: '4 поста >+200', c: '#4ade80', spark: TREND_24H.map(v => v * 0.8) },
          ].map(s => (
            <div key={s.l} style={{ borderRadius: 16, border: '1px solid var(--line)', background: 'rgba(255,255,255,0.015)', padding: 20 }}>
              <div style={{ fontSize: 13, color: 'var(--ink-dim)', fontWeight: 500 }}>{s.l}</div>
              <div className="tnum" style={{ fontSize: 36, fontWeight: 700, marginTop: 8, letterSpacing: '-0.02em' }}>{s.v}</div>
              <div className="mono" style={{ fontSize: 12, color: s.c, marginTop: 4 }}>{s.d}</div>
              <div style={{ marginTop: 10, height: 36 }}><Sparkline data={s.spark} color={s.c} width={220} height={36} dot={false} /></div>
            </div>
          ))}
        </div>

        {/* Period + platform */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 6, padding: 4, borderRadius: 12, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line)' }}>
            {[['24h', 'Сутки'], ['7d', '7 дней'], ['30d', '30 дней']].map(([id, l]) => (
              <button key={id} onClick={() => setPeriod(id)} style={{
                padding: '8px 14px', borderRadius: 9, border: 'none', cursor: 'pointer',
                background: period === id ? '#fff' : 'transparent',
                color: period === id ? '#000' : 'var(--ink-dim)', fontSize: 13, fontWeight: 500,
              }}>{l}</button>
            ))}
          </div>
          <Pill active={platform === 'all'} onClick={() => setPlatform('all')}>Все</Pill>
          {PLATFORMS.map(p => <Pill key={p.id} active={platform === p.id} onClick={() => setPlatform(p.id)} dot={p.color}>{p.label}</Pill>)}
        </div>

        <SectionHeader kicker="TOP MOVERS" title={<>Топ постов <span style={{ color: 'var(--ink-mute)', fontWeight: 400, marginLeft: 8 }}>(1067)</span></>} right={<Pill active>Прирост просмотров ↓</Pill>} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {POSTS.map((p, i) => <PostRow key={i} p={p} accent={accent} rank={i + 1} max={POSTS[0].delta} />)}
        </div>
      </main>
    </div>
  );
}

function PostRow({ p, accent, rank, max }) {
  const meta = PLATFORM_META[p.platform];
  const w = (p.delta / max) * 100;
  return (
    <div style={{
      position: 'relative', display: 'grid', gridTemplateColumns: '40px 80px 1fr auto auto', gap: 18, alignItems: 'center',
      padding: '14px 18px', borderRadius: 14, border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${w}%`, background: `linear-gradient(90deg, ${meta.color}10, transparent)`, opacity: 0.8 }} />
      <div className="mono tnum" style={{ position: 'relative', fontSize: 18, fontWeight: 700, color: rank <= 3 ? accent : 'var(--ink-mute)' }}>{String(rank).padStart(2, '0')}</div>
      <div style={{ position: 'relative', width: 64, height: 64, borderRadius: 8, background: `linear-gradient(135deg, ${meta.color}40, rgba(255,255,255,0.05))`, border: '1px solid var(--line)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'JetBrains Mono, monospace', fontSize: 9, color: 'var(--ink-mute)', letterSpacing: '0.1em' }}>POST</div>
      <div style={{ position: 'relative', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <PlatformGlyph id={p.platform} size={14} />
          <span style={{ fontSize: 14, fontWeight: 500 }}>{p.handle}</span>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', marginLeft: 'auto' }}>{p.date}</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.text}</div>
      </div>
      <div style={{ position: 'relative', display: 'flex', gap: 16, fontSize: 13 }}>
        <div className="mono tnum" style={{ color: 'var(--ink-dim)' }}>👁 {fmt(p.views)}</div>
        <div className="mono tnum" style={{ color: 'var(--ink-dim)' }}>♥ {fmt(p.likes)}</div>
        <div className="mono tnum" style={{ color: 'var(--ink-mute)' }}>ER {p.er.toFixed(1)}%</div>
      </div>
      <div className="mono tnum" style={{ position: 'relative', fontSize: 22, fontWeight: 600, color: '#4ade80' }}>+{p.delta}</div>
    </div>
  );
}

Object.assign(window, { AnalyticsScreen });
