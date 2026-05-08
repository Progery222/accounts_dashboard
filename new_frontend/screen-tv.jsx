// TV broadcast screen — auto-cycling fullscreen views.
// Three "scenes": Hero Atom, Platform Constellation, Top Accounts Leaderboard.
// All-data, no-input, transitions between scenes every 12s.

const { useEffect: useEffectTV, useState: useStateTV, useRef: useRefTV, useMemo: useMemoTV } = React;

function TVScreen({ tweaks, onExit }) {
  const mood = tweaks.tv_mood || 'mission';   // mission | bloomberg | calm
  const accent = tweaks.accent || '#6aa9ff';
  const accentSecondary = '#4ade80';

  const [scene, setScene] = useStateTV(0);
  const [now, setNow] = useStateTV(new Date());
  const [pulse, setPulse] = useStateTV(0);

  const SCENES = ['atom', 'pulse', 'top'];

  useEffectTV(() => {
    const id = setInterval(() => setScene(s => (s + 1) % SCENES.length), 14000);
    return () => clearInterval(id);
  }, []);
  useEffectTV(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffectTV(() => {
    const id = setInterval(() => setPulse(p => p + 1), 2200);
    return () => clearInterval(id);
  }, []);

  const moodTone = mood === 'bloomberg'
    ? { bg: '#000', accent: '#ffb000', surface: 'rgba(255,255,255,0.02)' }
    : mood === 'calm'
    ? { bg: '#070a10', accent: '#a8c9ff', surface: 'rgba(255,255,255,0.02)' }
    : { bg: '#050608', accent: accent, surface: 'rgba(255,255,255,0.025)' };

  return (
    <div style={{ position: 'fixed', inset: 0, background: moodTone.bg, color: '#fff', overflow: 'hidden', fontFamily: 'Space Grotesk, sans-serif' }} data-screen-label="TV Broadcast">
      <ParticleField count={mood === 'calm' ? 80 : 50} color={moodTone.accent} opacity={mood === 'bloomberg' ? 0.25 : 0.6} />
      <AtomicGrid opacity={mood === 'bloomberg' ? 0.025 : 0.04} size={64} />

      <TVHeader now={now} accent={moodTone.accent} mood={mood} onExit={onExit} />

      <div style={{ position: 'absolute', top: 110, left: 0, right: 0, bottom: 110 }}>
        <SceneSwitch scene={SCENES[scene]} accent={moodTone.accent} mood={mood} pulse={pulse} />
      </div>

      <TVTicker accent={moodTone.accent} />
      <TVSceneIndicator total={SCENES.length} current={scene} accent={moodTone.accent} />
    </div>
  );
}

// ── Header: brand, time, autoupdate state ──────────────────
function TVHeader({ now, accent, mood, onExit }) {
  const t = now.toTimeString().slice(0, 8);
  const d = now.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', weekday: 'long' });
  return (
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, padding: '32px 56px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', zIndex: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.01em' }}>AccountsStats <span style={{ color: accent }}>/</span> Live</div>
          <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.18em', textTransform: 'uppercase', marginTop: 2 }}>BROADCAST · 163 ACCOUNTS · 6 PLATFORMS</div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 9, height: 9, borderRadius: 999, background: accent, boxShadow: `0 0 14px ${accent}` }} className="pulse-dot" />
          <span className="mono" style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)', letterSpacing: '0.2em' }}>AUTO · 06:00 / 12:00 / 18:00</span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="mono tnum" style={{ fontSize: 30, fontWeight: 500, color: '#fff', letterSpacing: '0.02em' }}>{t}</div>
          <div className="mono" style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: '0.18em', textTransform: 'uppercase', marginTop: 2 }}>{d} · MSK</div>
        </div>
        <button onClick={onExit} style={{
          padding: '10px 18px', borderRadius: 999, background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)',
          fontSize: 12, letterSpacing: '0.16em', textTransform: 'uppercase', cursor: 'pointer',
          fontFamily: 'JetBrains Mono, monospace',
        }}>Exit TV</button>
      </div>
      <style>{`
        .pulse-dot { animation: pulseDot 1.6s ease-in-out infinite; }
        @keyframes pulseDot { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.7); } }
      `}</style>
    </div>
  );
}

function AtomLogo({ size = 44, accent = '#6aa9ff' }) {
  return (
    <svg viewBox="0 0 100 100" width={size} height={size}>
      <ellipse cx="50" cy="50" rx="42" ry="16" fill="none" stroke={accent} strokeWidth="1.5" opacity="0.7" />
      <ellipse cx="50" cy="50" rx="42" ry="16" fill="none" stroke={accent} strokeWidth="1.5" opacity="0.7" transform="rotate(60 50 50)" />
      <ellipse cx="50" cy="50" rx="42" ry="16" fill="none" stroke={accent} strokeWidth="1.5" opacity="0.7" transform="rotate(-60 50 50)" />
      <circle cx="50" cy="50" r="6" fill={accent} />
      <circle cx="50" cy="50" r="3" fill="#fff" />
    </svg>
  );
}

// ── Scene switcher ─────────────────────────────────────────
function SceneSwitch({ scene, accent, mood, pulse }) {
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div key={scene} style={{ position: 'absolute', inset: 0, animation: 'sceneIn .9s cubic-bezier(.4,0,.2,1)' }}>
        {scene === 'atom' && <SceneAtom accent={accent} mood={mood} />}
        {scene === 'pulse' && <ScenePulse accent={accent} mood={mood} pulse={pulse} />}
        {scene === 'top' && <SceneTop accent={accent} mood={mood} />}
      </div>
      <style>{`
        @keyframes sceneIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  );
}

// ── SCENE 1: Hero atom + 4 totals around ───────────────────
function SceneAtom({ accent, mood }) {
  const orbits = [
    { rx: 220, ry: 80,  rot: 0,    color: '#4ade80', opacity: 0.5, dur: 32, particleR: 9 },
    { rx: 220, ry: 80,  rot: 60,   color: '#ec4899', opacity: 0.5, dur: 26, particleR: 8 },
    { rx: 220, ry: 80,  rot: -60,  color: '#f59e0b', opacity: 0.5, dur: 38, particleR: 7 },
    { rx: 290, ry: 110, rot: 30,   color: accent,   opacity: 0.3, dur: 48, particleR: 5, dash: '2 8' },
  ];
  const items = [
    { label: 'ПОДПИСЧИКИ',  value: TOTAL.followers.value,  delta: TOTAL.followers.delta,  color: '#4ade80', spark: TREND_24H.map(v => v * 0.18) },
    { label: 'TROUGH',   value: TOTAL.views.value,      delta: TOTAL.views.delta,      color: '#ec4899', spark: TREND_24H },
    { label: 'ЛАЙКИ',       value: TOTAL.likes.value,      delta: TOTAL.likes.delta,      color: '#f59e0b', spark: TREND_24H.map(v => v * 0.5) },
    { label: 'ПУБЛИКАЦИИ',  value: TOTAL.posts.value,      delta: TOTAL.posts.delta,      color: accent,    spark: TREND_24H.map(v => v * 0.3) },
  ];
  return (
    <div style={{ width: '100%', height: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', gridTemplateRows: '1fr 1fr', gap: 28, padding: '0 56px' }}>
      <BigStat {...items[0]} align="left" />
      <BigStat {...items[1]} align="left" />
      <BigStat {...items[2]} align="left" />
      <BigStat {...items[3]} align="left" />
    </div>
  );
}

function BigStat({ label, value, delta, color, spark, align }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      padding: '36px 44px 28px', borderRadius: 20,
      background: 'linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.005))',
      border: '1px solid rgba(255,255,255,0.06)',
      textAlign: 'left',
      position: 'relative', overflow: 'hidden',
      minWidth: 0, minHeight: 0,
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, width: 4, bottom: 0, background: color, opacity: 0.55 }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.7)', fontWeight: 500, textTransform: 'capitalize' }}>{label.toLowerCase()}</div>
        <div className="mono tnum" style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', letterSpacing: '0.16em' }}>24H</div>
      </div>
      <div className="tnum" style={{ flex: 1, display: 'flex', alignItems: 'center', fontSize: 'clamp(80px, 11vw, 168px)', fontWeight: 700, color: '#fff', lineHeight: 0.9, letterSpacing: '-0.04em', marginTop: 12 }}>
        {fmt(value)}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 18, marginTop: 12 }}>
        <div className="mono tnum" style={{ fontSize: 28, color: color, fontWeight: 500, whiteSpace: 'nowrap' }}>
          ▲ +{fmt(delta)}
        </div>
        <div style={{ flex: 1, height: 64, minWidth: 0 }}>
          <ResponsiveSpark data={spark} color={color} />
        </div>
      </div>
    </div>
  );
}

function ResponsiveSpark({ data, color }) {
  const w = 600, h = 60;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - ((v - min) / (max - min || 1)) * (h - 8) - 4]);
  const path = pts.map((p, i) => i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`).join(' ');
  const area = `${path} L${w},${h} L0,${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
      <defs>
        <linearGradient id={`sf-${color.replace('#','')}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#sf-${color.replace('#','')})`} />
      <path d={path} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// ── SCENE 2: Pulse / dynamics — sparklines per platform & profile ──
function ScenePulse({ accent, mood, pulse }) {
  return (
    <div style={{ width: '100%', height: '100%', padding: '0 56px', display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 28 }}>
      {/* Left: big trend chart */}
      <div style={{ borderRadius: 20, border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.015)', padding: 32, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
          <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.24em' }}>VIEWS · LAST 24H</div>
            <div className="tnum" style={{ fontSize: 88, fontWeight: 700, marginTop: 8, lineHeight: 0.95, letterSpacing: '-0.03em' }}>+{fmt(TOTAL.views.delta)}</div>
            <div className="mono" style={{ fontSize: 16, color: '#4ade80', marginTop: 6 }}>▲ 5.7% vs prev. day</div>
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            {[
              { k: 'PEAK', v: '14:00', c: accent },
              { k: 'TROUGH', v: '04:00', c: 'rgba(255,255,255,0.4)' },
              { k: 'AVG/H', v: '521', c: '#4ade80' },
            ].map(s => (
              <div key={s.k} style={{ textAlign: 'right' }}>
                <div className="mono" style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: '0.24em' }}>{s.k}</div>
                <div className="tnum" style={{ fontSize: 22, fontWeight: 600, color: s.c, marginTop: 2 }}>{s.v}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ flex: 1, marginTop: 24, position: 'relative', minHeight: 0 }}>
          <BigChart accent={accent} />
        </div>
      </div>
      {/* Right: per-platform pulses */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.24em', marginBottom: 4 }}>PLATFORM PULSE</div>
        {PLATFORMS.slice(0, 5).map((p, i) => {
          const value = Math.round(TOTAL.views.delta * p.share);
          const data = TREND_24H.map((v, idx) => v * (p.share + 0.4) + Math.sin(idx + i) * 30);
          return (
            <div key={p.id} style={{
              display: 'grid', gridTemplateColumns: '110px 1fr 110px', alignItems: 'center', gap: 16,
              padding: '14px 18px', borderRadius: 14, background: 'rgba(255,255,255,0.015)',
              border: '1px solid rgba(255,255,255,0.05)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, background: p.color, boxShadow: `0 0 10px ${p.color}` }} />
                <span style={{ fontSize: 15, fontWeight: 500 }}>{p.label}</span>
              </div>
              <div style={{ height: 32 }}><Sparkline data={data} color={p.color} width={300} height={32} dot={false} fill /></div>
              <div className="mono tnum" style={{ fontSize: 18, color: p.color, textAlign: 'right', fontWeight: 600 }}>+{fmt(value)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BigChart({ accent }) {
  const w = 800, h = 320;
  const data = TREND_24H;
  const max = Math.max(...data);
  const stepX = w / (data.length - 1);
  const points = data.map((v, i) => [i * stepX, h - (v / max) * (h - 30) - 10]);
  const path = points.map((p, i) => i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`).join(' ');
  const areaPath = `${path} L${w},${h} L0,${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <defs>
        <linearGradient id="bigfill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.5" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* gridlines */}
      {[0.25, 0.5, 0.75].map(y => (
        <line key={y} x1="0" x2={w} y1={h * y} y2={h * y} stroke="rgba(255,255,255,0.05)" strokeDasharray="2 6" />
      ))}
      {/* hour labels */}
      {[0, 6, 12, 18, 23].map(i => (
        <text key={i} x={i * stepX} y={h - 2} fill="rgba(255,255,255,0.3)" fontSize="10" fontFamily="JetBrains Mono, monospace">{String(i).padStart(2, '0')}:00</text>
      ))}
      <path d={areaPath} fill="url(#bigfill)" />
      <path d={path} fill="none" stroke={accent} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {/* peak dot */}
      <circle cx={points[points.length - 1][0]} cy={points[points.length - 1][1]} r="6" fill={accent} stroke="#050608" strokeWidth="3">
        <animate attributeName="r" values="6;9;6" dur="1.6s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

// ── SCENE 3: Top accounts leaderboard ──────────────────────
function SceneTop({ accent }) {
  const top = [...ACCOUNTS].sort((a, b) => b.dViews - a.dViews).slice(0, 8);
  const max = top[0].dViews;
  return (
    <div style={{ width: '100%', height: '100%', padding: '0 56px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
      {/* Leaderboard list */}
      <div>
        <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.24em', marginBottom: 18 }}>TOP MOVERS · 24H · BY VIEW DELTA</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {top.map((a, i) => {
            const w = (a.dViews / max) * 100;
            const meta = PLATFORM_META[a.platform];
            const prof = PROFILE_META[a.profile];
            return (
              <div key={a.handle} style={{
                position: 'relative', padding: '14px 20px', borderRadius: 14,
                background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)',
                overflow: 'hidden',
              }}>
                <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(90deg, ${prof.color}22, transparent ${Math.min(95, w + 20)}%)`, opacity: 0.7 }} />
                <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: '36px 52px 1fr auto auto', alignItems: 'center', gap: 16 }}>
                  <div className="mono tnum" style={{ fontSize: 22, fontWeight: 700, color: i < 3 ? accent : 'rgba(255,255,255,0.45)' }}>{String(i + 1).padStart(2, '0')}</div>
                  <span style={{
                    width: 44, height: 44, borderRadius: 999,
                    background: `linear-gradient(135deg, ${meta.color}55, ${prof.color}40)`,
                    border: `1px solid ${meta.color}55`,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 16, fontWeight: 700, color: '#fff',
                    boxShadow: `0 0 18px ${prof.color}30`,
                  }}>{a.name.charAt(0).toUpperCase()}</span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 19, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.handle}</div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center' }}>
                      <span className="mono" style={{ fontSize: 11, color: meta.color, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{meta.label}</span>
                      <span style={{ width: 3, height: 3, borderRadius: 999, background: 'rgba(255,255,255,0.3)' }} />
                      <span className="mono" style={{ fontSize: 11, color: prof.color, letterSpacing: '0.1em' }}>{prof.label}</span>
                    </div>
                  </div>
                  <div className="mono tnum" style={{ fontSize: 18, color: 'rgba(255,255,255,0.65)', textAlign: 'right', minWidth: 64 }}>{fmt(a.views)}</div>
                  <div className="mono tnum" style={{ fontSize: 22, color: '#4ade80', fontWeight: 600, textAlign: 'right', minWidth: 90 }}>+{fmt(a.dViews)}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right column: distribution + profiles */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        <div style={{ borderRadius: 20, border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.015)', padding: 28 }}>
          <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.24em', marginBottom: 18 }}>BY PROFILE</div>
          <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
            {PROFILES.map(p => (
              <div key={p.id} style={{ textAlign: 'center' }}>
                <RadialDial value={p.accounts / 162} size={140} color={p.color} label={p.accounts} sub={p.label} />
              </div>
            ))}
          </div>
        </div>
        <div style={{ borderRadius: 20, border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.015)', padding: 28, flex: 1 }}>
          <div className="mono" style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', letterSpacing: '0.24em', marginBottom: 18 }}>PLATFORM DISTRIBUTION</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {PLATFORMS.map(p => (
              <div key={p.id} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 60px', alignItems: 'center', gap: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color }} />
                  <span style={{ fontSize: 14 }}>{p.label}</span>
                </div>
                <div style={{ height: 8, borderRadius: 2, background: 'rgba(255,255,255,0.04)', overflow: 'hidden', position: 'relative' }}>
                  <div style={{ position: 'absolute', inset: 0, width: `${p.share * 100}%`, background: p.color, opacity: 0.85 }} />
                </div>
                <div className="mono tnum" style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)', textAlign: 'right' }}>{p.accounts}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Bottom ticker ──────────────────────────────────────────
function TVTicker({ accent }) {
  const items = useMemoTV(() => {
    return ACCOUNTS.filter(a => a.dViews > 0).slice(0, 10).map(a => `${a.handle} +${fmt(a.dViews)} VIEWS`);
  }, []);
  return (
    <div style={{ position: 'absolute', bottom: 28, left: 0, right: 0, display: 'flex', alignItems: 'center', gap: 20, padding: '0 56px' }}>
      <div style={{ flexShrink: 0, padding: '8px 14px', borderRadius: 999, background: accent, color: '#000', fontSize: 11, fontWeight: 700, letterSpacing: '0.18em', fontFamily: 'JetBrains Mono, monospace' }}>LIVE</div>
      <div style={{ flex: 1, overflow: 'hidden', maskImage: 'linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent)' }}>
        <div className="mono" style={{ display: 'flex', gap: 48, whiteSpace: 'nowrap', animation: 'tickerScroll 80s linear infinite', fontSize: 15, color: 'rgba(255,255,255,0.7)', letterSpacing: '0.06em' }}>
          {[...items, ...items, ...items].map((it, i) => (
            <span key={i} style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: accent }}>◆</span> {it}
            </span>
          ))}
        </div>
      </div>
      <style>{`
        @keyframes tickerScroll { from { transform: translateX(0); } to { transform: translateX(-33.333%); } }
      `}</style>
    </div>
  );
}

function TVSceneIndicator({ total, current, accent }) {
  return (
    <div style={{ position: 'absolute', top: 110, right: 56, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} style={{
          width: i === current ? 32 : 12, height: 3, borderRadius: 2,
          background: i === current ? accent : 'rgba(255,255,255,0.15)',
          transition: 'all 0.4s ease',
        }} />
      ))}
      <div className="mono" style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.2em', marginTop: 6 }}>SCENE {current + 1}/{total}</div>
    </div>
  );
}

Object.assign(window, { TVScreen });
