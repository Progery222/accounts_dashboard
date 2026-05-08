// Accounts list screen — atomic-themed redesign of the table view.

const { useState: useStateAcc, useMemo: useMemoAcc } = React;

function AccountsScreen({ tweaks }) {
  const accent = tweaks.accent || '#6aa9ff';
  const view = tweaks.accounts_view || 'table'; // table | cards
  const [platform, setPlatform] = useStateAcc('all');
  const [profile, setProfile] = useStateAcc('all');
  const [status, setStatus] = useStateAcc('all');
  const [tab, setTab] = useStateAcc('accounts');

  const filtered = useMemoAcc(() => {
    return ACCOUNTS.filter(a =>
      (platform === 'all' || a.platform === platform) &&
      (profile === 'all' || a.profile === profile)
    );
  }, [platform, profile]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }} data-screen-label="Accounts List">
      <TopBar accent={accent} />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '280px 1fr', gap: 0 }}>
        <Sidebar profile={profile} setProfile={setProfile} tab={tab} setTab={setTab} accent={accent} />
        <main style={{ padding: '28px 36px 60px', minWidth: 0 }}>
          <FilterBar platform={platform} setPlatform={setPlatform} status={status} setStatus={setStatus} accent={accent} />
          {view === 'table'
            ? <AccountsTable rows={filtered} accent={accent} />
            : <AccountsCards rows={filtered} accent={accent} />}
        </main>
      </div>
    </div>
  );
}

function TopBar({ accent }) {
  const stats = [
    { label: 'ПОДПИСЧИКИ', value: TOTAL.followers.value, delta: TOTAL.followers.delta, color: '#4ade80' },
    { label: 'ПРОСМОТРЫ',  value: TOTAL.views.value,     delta: TOTAL.views.delta,     color: '#ec4899' },
    { label: 'ЛАЙКИ',      value: TOTAL.likes.value,     delta: TOTAL.likes.delta,     color: '#f59e0b' },
    { label: 'ПУБЛИКАЦИИ', value: TOTAL.posts.value,     delta: TOTAL.posts.delta,     color: accent },
  ];
  return (
    <header style={{
      position: 'sticky', top: 0, zIndex: 50, padding: '18px 36px',
      background: 'rgba(5,6,8,0.85)', backdropFilter: 'blur(14px)',
      borderBottom: '1px solid var(--line)',
      display: 'grid', gridTemplateColumns: '260px 1fr auto', gap: 32, alignItems: 'center',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>AccountsStats</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-mute)', letterSpacing: '0.2em', textTransform: 'uppercase' }}>v2.0 · ATOMIC</div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {stats.map((s, i) => (
          <React.Fragment key={s.label}>
            {i > 0 && <span style={{ width: 1, height: 36, background: 'var(--line)' }} />}
            <div style={{ flex: 1, padding: '0 14px' }}>
              <div className="mono" style={{ fontSize: 10, color: 'var(--ink-mute)', letterSpacing: '0.18em' }}>{s.label}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
                <span className="tnum" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>{fmt(s.value)}</span>
                <span className="mono tnum" style={{ fontSize: 12, color: s.color }}>+{fmt(s.delta)}</span>
              </div>
            </div>
          </React.Fragment>
        ))}
        <div style={{ width: 1, height: 36, background: 'var(--line)' }} />
        <div style={{ padding: '0 14px' }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-mute)', letterSpacing: '0.18em' }}>АККАУНТОВ</div>
          <div className="tnum" style={{ fontSize: 22, fontWeight: 600, marginTop: 2 }}>{TOTAL.accounts}</div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <Btn>↻ Обновить всё</Btn>
        <Btn accent={accent}><span style={{ width: 8, height: 8, borderRadius: 999, background: '#4ade80', display: 'inline-block', marginRight: 6, boxShadow: '0 0 8px #4ade80' }} />Автообновление</Btn>
        <Btn>+ Список</Btn>
        <Btn primary accent={accent}>+ Добавить</Btn>
      </div>
    </header>
  );
}

function AtomLogoMini({ size = 32, accent }) {
  return (
    <svg viewBox="0 0 100 100" width={size} height={size}>
      <ellipse cx="50" cy="50" rx="40" ry="14" fill="none" stroke={accent} strokeWidth="2" opacity="0.7" />
      <ellipse cx="50" cy="50" rx="40" ry="14" fill="none" stroke={accent} strokeWidth="2" opacity="0.7" transform="rotate(60 50 50)" />
      <circle cx="50" cy="50" r="8" fill={accent} />
    </svg>
  );
}

function Btn({ children, primary, accent = '#6aa9ff', onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: '10px 16px', borderRadius: 12,
      background: primary ? accent : 'rgba(255,255,255,0.04)',
      color: primary ? '#000' : 'var(--ink)',
      border: primary ? 'none' : '1px solid var(--line)',
      fontSize: 13, fontWeight: primary ? 600 : 500, cursor: 'pointer',
      display: 'inline-flex', alignItems: 'center',
      transition: 'all .15s',
    }}>{children}</button>
  );
}

function Sidebar({ profile, setProfile, tab, setTab, accent }) {
  return (
    <aside style={{ borderRight: '1px solid var(--line)', padding: '24px 20px', position: 'sticky', top: 80, height: 'calc(100vh - 80px)' }}>
      <div style={{ display: 'flex', gap: 4, padding: 4, background: 'rgba(255,255,255,0.025)', borderRadius: 12, border: '1px solid var(--line)' }}>
        {[{ id: 'accounts', label: 'Аккаунты' }, { id: 'analytics', label: 'Аналитика' }].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: '8px 12px', borderRadius: 9, border: 'none', cursor: 'pointer',
            background: tab === t.id ? '#fff' : 'transparent',
            color: tab === t.id ? '#000' : 'var(--ink-dim)',
            fontSize: 13, fontWeight: tab === t.id ? 600 : 500,
          }}>{t.label}</button>
        ))}
      </div>
      <div style={{ marginTop: 24 }}>
        <div style={{ position: 'relative', marginBottom: 14 }}>
          <input placeholder="Поиск профилей" style={{
            width: '100%', padding: '10px 14px 10px 34px', borderRadius: 10,
            background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line)',
            color: 'var(--ink)', fontSize: 13, fontFamily: 'inherit',
          }} />
          <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-mute)', fontSize: 12 }}>⌕</span>
        </div>
        <SidebarItem active={profile === 'all'} onClick={() => setProfile('all')} label="Все профили" count={162} dot="ring" accent={accent} />
        <SidebarItem active={profile === 'none'} onClick={() => setProfile('none')} label="Без профиля" count={0} dim />
        <div style={{ height: 1, background: 'var(--line)', margin: '14px 0' }} />
        {PROFILES.map(p => (
          <SidebarItem key={p.id} active={profile === p.id} onClick={() => setProfile(p.id)} label={p.label} count={p.accounts} color={p.color} />
        ))}
      </div>
    </aside>
  );
}

function SidebarItem({ active, onClick, label, count, color, dot, dim, accent }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
      padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
      background: active ? 'rgba(255,255,255,0.04)' : 'transparent',
      border: `1px solid ${active ? 'var(--line-2)' : 'transparent'}`,
      marginBottom: 2,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {color
          ? <span style={{ width: 22, height: 22, borderRadius: 999, background: `${color}26`, color, fontSize: 11, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>{label.charAt(0)}</span>
          : <span style={{ width: 22, height: 22, borderRadius: 999, border: `1.5px solid ${active ? 'var(--ink-dim)' : 'var(--line-2)'}`, opacity: dim ? 0.4 : 1 }} />
        }
        <span style={{ fontSize: 14, color: dim ? 'var(--ink-mute)' : 'var(--ink)' }}>{label}</span>
      </div>
      <span className="mono tnum" style={{ fontSize: 12, color: 'var(--ink-mute)' }}>{count}</span>
    </div>
  );
}

function FilterBar({ platform, setPlatform, status, setStatus, accent }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, position: 'relative' }}>
          <input placeholder="Поиск аккаунтов…" style={{
            width: '100%', padding: '12px 16px 12px 40px', borderRadius: 12,
            background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line)',
            color: 'var(--ink)', fontSize: 14, fontFamily: 'inherit',
          }} />
          <span style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-mute)' }}>⌕</span>
        </div>
        <Pill active={platform === 'all'} onClick={() => setPlatform('all')}>Все</Pill>
        {PLATFORMS.slice(0, 5).map(p => (
          <Pill key={p.id} active={platform === p.id} onClick={() => setPlatform(p.id)} dot={p.color}>{p.label}</Pill>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Btn>↺ Сбросить фильтры</Btn>
        <Pill active={status === 'all'} onClick={() => setStatus('all')}>Все статусы</Pill>
        <Pill active={status === 'avail'} onClick={() => setStatus('avail')}>Доступные</Pill>
        <Pill active={status === 'unavail'} onClick={() => setStatus('unavail')}>Недоступные</Pill>
      </div>
    </div>
  );
}

function Pill({ active, onClick, children, dot }) {
  return (
    <button onClick={onClick} style={{
      padding: '8px 14px', borderRadius: 999, cursor: 'pointer',
      background: active ? '#fff' : 'rgba(255,255,255,0.025)',
      color: active ? '#000' : 'var(--ink-dim)',
      border: '1px solid ' + (active ? '#fff' : 'var(--line)'),
      fontSize: 13, fontWeight: active ? 600 : 500,
      display: 'inline-flex', alignItems: 'center', gap: 6,
    }}>
      {dot && <span style={{ width: 6, height: 6, borderRadius: 999, background: dot }} />}
      {children}
    </button>
  );
}

function AccountsTable({ rows, accent }) {
  return (
    <div style={{ borderRadius: 14, border: '1px solid var(--line)', background: 'rgba(255,255,255,0.015)', overflow: 'hidden' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 0.8fr 1fr 0.8fr 0.8fr 1.1fr',
        padding: '14px 20px', gap: 16, borderBottom: '1px solid var(--line)',
        fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.18em', textTransform: 'uppercase',
        fontFamily: 'JetBrains Mono, monospace',
      }}>
        <div>Аккаунт</div>
        <div>Платформа</div>
        <div>Профиль</div>
        <div style={{ textAlign: 'right' }}>Подписчики</div>
        <div style={{ textAlign: 'right', color: accent }}>Просмотры ↓</div>
        <div style={{ textAlign: 'right' }}>Лайки</div>
        <div style={{ textAlign: 'right' }}>Публ.</div>
        <div>Обновлён</div>
      </div>
      {rows.map((a, i) => (
        <AccountRow key={a.handle} a={a} i={i} />
      ))}
    </div>
  );
}

function AccountRow({ a, i }) {
  const meta = PLATFORM_META[a.platform];
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 0.8fr 1fr 0.8fr 0.8fr 1.1fr',
      padding: '16px 20px', gap: 16, alignItems: 'center',
      borderBottom: i < ACCOUNTS.length - 1 ? '1px solid var(--line)' : 'none',
      fontSize: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{
          width: 36, height: 36, borderRadius: 999,
          background: `linear-gradient(135deg, ${meta.color}40, ${PROFILE_META[a.profile].color}30)`,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700, color: '#fff',
          border: `1px solid ${meta.color}40`,
        }}>{a.name.charAt(0).toUpperCase()}</span>
        <div>
          <div style={{ fontWeight: 500 }}>{a.name}</div>
          <div className="mono" style={{ fontSize: 12, color: 'var(--ink-mute)' }}>{a.handle}</div>
        </div>
      </div>
      <div><PlatformGlyph id={a.platform} /></div>
      <div><ProfileBadge id={a.profile} /></div>
      <div className="mono tnum" style={{ textAlign: 'right', color: a.followers ? '#fff' : 'var(--ink-mute)' }}>{a.followers ?? '—'}</div>
      <div style={{ textAlign: 'right' }}>
        <div className="mono tnum" style={{ fontSize: 15, fontWeight: 500 }}>{fmt(a.views)}</div>
        <div className="mono tnum" style={{ fontSize: 12, color: '#4ade80' }}>+{fmt(a.dViews)}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className="mono tnum">{fmt(a.likes)}</div>
        <div className="mono tnum" style={{ fontSize: 12, color: a.dLikes >= 0 ? '#4ade80' : 'var(--danger)' }}>{a.dLikes >= 0 ? '+' : ''}{fmt(a.dLikes)}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className="mono tnum">{fmt(a.posts)}</div>
        <div className="mono tnum" style={{ fontSize: 12, color: '#4ade80' }}>+{fmt(a.dPosts)}</div>
      </div>
      <div className="mono" style={{ fontSize: 12, color: 'var(--ink-mute)' }}>{a.updated}</div>
    </div>
  );
}

function AccountsCards({ rows, accent }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
      {rows.map(a => {
        const meta = PLATFORM_META[a.platform];
        const prof = PROFILE_META[a.profile];
        return (
          <div key={a.handle} style={{
            padding: 18, borderRadius: 14,
            background: `linear-gradient(180deg, ${prof.color}10, rgba(255,255,255,0.01))`,
            border: '1px solid var(--line)',
            position: 'relative', overflow: 'hidden',
          }}>
            <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: 2, background: prof.color, opacity: 0.6 }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ width: 36, height: 36, borderRadius: 999, background: `linear-gradient(135deg, ${meta.color}40, ${prof.color}30)`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, border: `1px solid ${meta.color}40` }}>{a.name.charAt(0).toUpperCase()}</span>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>{a.name}</div>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)' }}>{a.handle}</div>
                </div>
              </div>
              <ProfileBadge id={a.profile} dense />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
              {[['Views', a.views, a.dViews, '#ec4899'], ['Likes', a.likes, a.dLikes, '#f59e0b'], ['Posts', a.posts, a.dPosts, accent]].map(([l, v, d, c]) => (
                <div key={l}>
                  <div className="mono" style={{ fontSize: 9, color: 'var(--ink-mute)', letterSpacing: '0.18em' }}>{l.toUpperCase()}</div>
                  <div className="mono tnum" style={{ fontSize: 17, fontWeight: 600 }}>{fmt(v)}</div>
                  <div className="mono tnum" style={{ fontSize: 11, color: d >= 0 ? '#4ade80' : 'var(--danger)' }}>{d >= 0 ? '+' : ''}{fmt(d)}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <PlatformGlyph id={a.platform} size={16} />
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)' }}>{a.updated}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, { AccountsScreen, TopBar, Sidebar, FilterBar });
