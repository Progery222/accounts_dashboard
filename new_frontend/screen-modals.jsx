// Modal screens — Add list, Schedule, Add account form.

const { useState: useStateMd } = React;

function ModalsScreen({ tweaks }) {
  const accent = tweaks.accent || '#6aa9ff';
  const [active, setActive] = useStateMd('add_list');
  return (
    <div style={{ minHeight: '100vh', position: 'relative' }} data-screen-label="Modals">
      <TopBar accent={accent} />
      <main style={{ padding: '28px 36px 60px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 22 }}>
          {[['add_list', 'Добавить список'], ['schedule', 'Расписание'], ['add_one', 'Добавить аккаунт']].map(([id, l]) => (
            <Pill key={id} active={active === id} onClick={() => setActive(id)}>{l}</Pill>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
          {active === 'add_list' && <AddListModal accent={accent} />}
          {active === 'schedule' && <ScheduleModal accent={accent} />}
          {active === 'add_one' && <AddOneInline accent={accent} />}
        </div>
      </main>
    </div>
  );
}

function ModalShell({ title, kicker, children, accent, width = 560 }) {
  return (
    <div style={{
      width, padding: 32, borderRadius: 22,
      background: 'linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))',
      border: '1px solid var(--line-2)', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} />
      <ParticleField count={20} color={accent} opacity={0.3} />
      <div style={{ position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 22 }}>
          <div>
            {kicker && <div className="mono" style={{ fontSize: 10, color: 'var(--ink-mute)', letterSpacing: '0.24em' }}>{kicker}</div>}
            <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4, letterSpacing: '-0.01em' }}>{title}</div>
          </div>
          <button style={{ width: 32, height: 32, borderRadius: 999, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--line)', color: 'var(--ink-dim)', cursor: 'pointer', fontSize: 14 }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function AddListModal({ accent }) {
  return (
    <ModalShell title="Добавить список аккаунтов" kicker="BATCH IMPORT" accent={accent}>
      <div style={{ fontSize: 13, color: 'var(--ink-dim)', marginBottom: 12 }}>Вставь URL аккаунтов — по одному на строку или через запятую</div>
      <textarea defaultValue={'https://www.tiktok.com/@username\nhttps://www.youtube.com/@channel\nhttps://www.threads.com/@user\nhttps://t.me/channel'} style={{
        width: '100%', minHeight: 160, padding: 16, borderRadius: 12,
        background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line-2)',
        color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', lineHeight: 1.6, resize: 'vertical',
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 18, flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em' }}>ПРОФИЛЬ</span>
        <ProfilePicker accent={accent} />
        <button style={{ padding: '8px 14px', borderRadius: 999, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--line)', color: 'var(--ink-dim)', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit', display: 'inline-flex', alignItems: 'center', gap: 6 }}>+ Новый</button>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 28 }}>
        <button style={{ padding: '8px 0', background: 'transparent', border: 'none', color: 'var(--ink-dim)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Отмена</button>
        <button style={{ padding: '12px 28px', borderRadius: 12, background: accent, color: '#000', border: 'none', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>Импортировать</button>
      </div>
    </ModalShell>
  );
}

function ScheduleModal({ accent }) {
  const [mode, setMode] = useStateMd('time');
  const [skip, setSkip] = useStateMd('3h');
  const [auto, setAuto] = useStateMd(true);
  const times = ['06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '00:00'];
  return (
    <ModalShell title="Расписание обновлений" kicker="AUTOMATION" accent={accent} width={620}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', borderRadius: 12, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line)', marginBottom: 18 }}>
        <span style={{ fontSize: 14, fontWeight: 500 }}>Автообновление</span>
        <button onClick={() => setAuto(!auto)} style={{
          width: 50, height: 26, borderRadius: 999, background: auto ? '#4ade80' : 'rgba(255,255,255,0.1)',
          border: 'none', cursor: 'pointer', position: 'relative', transition: 'all .2s',
        }}>
          <span style={{ position: 'absolute', top: 3, left: auto ? 27 : 3, width: 20, height: 20, borderRadius: 999, background: '#fff', transition: 'all .2s' }} />
        </button>
      </div>

      <div style={{ padding: 16, borderRadius: 12, background: 'rgba(255,255,255,0.015)', border: '1px solid var(--line)', marginBottom: 18 }}>
        <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', cursor: 'pointer' }}>
          <span style={{ width: 18, height: 18, borderRadius: 5, background: '#4ade80', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>
            <span style={{ color: '#000', fontSize: 11, fontWeight: 800 }}>✓</span>
          </span>
          <span>
            <div style={{ fontSize: 14, color: 'var(--ink)' }}>После завершения автообновления сохранять CSV-отчёт</div>
            <div style={{ fontSize: 12, color: 'var(--ink-mute)', marginTop: 4, lineHeight: 1.5 }}>Файл хранится на сервере; утром откройте окно и нажмите «Скачать».</div>
          </span>
        </label>
      </div>

      <div style={{ display: 'flex', gap: 6, padding: 4, borderRadius: 12, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line)', marginBottom: 16 }}>
        {[['hours', 'Каждые N часов'], ['time', 'В определённое время']].map(([id, l]) => (
          <button key={id} onClick={() => setMode(id)} style={{
            flex: 1, padding: '10px 14px', borderRadius: 9, border: 'none', cursor: 'pointer',
            background: mode === id ? '#fff' : 'transparent',
            color: mode === id ? '#000' : 'var(--ink-dim)', fontSize: 13, fontWeight: 500,
          }}>{l}</button>
        ))}
      </div>

      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em', marginBottom: 10 }}>ВРЕМЯ ОБНОВЛЕНИЯ · MSK</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 18 }}>
        {times.map(t => (
          <Pill key={t} active={t === '06:00'}>{t}</Pill>
        ))}
        <Pill>+ Добавить</Pill>
      </div>

      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em', marginBottom: 10 }}>ПРОПУСКАТЬ НЕДАВНО ОБНОВЛЁННЫЕ</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 26 }}>
        {['Не пропускать', '< 1ч', '< 3ч', '< 6ч', '< 12ч', '< 24ч'].map(t => (
          <Pill key={t} active={t === skip || (t === '< 3ч' && skip === '3h')} onClick={() => setSkip(t)}>{t}</Pill>
        ))}
      </div>

      <button style={{ width: '100%', padding: 16, borderRadius: 12, background: accent, color: '#000', border: 'none', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>Запустить автообновление сейчас</button>
    </ModalShell>
  );
}

function ProfilePicker({ accent }) {
  const [val, setVal] = useStateMd('none');
  const [open, setOpen] = useStateMd(false);
  const opts = [{ id: 'none', label: 'Без профиля', color: '#525a70' }, ...PROFILES];
  const sel = opts.find(o => o.id === val);
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)} style={{
        padding: '8px 14px', borderRadius: 999,
        background: 'rgba(255,255,255,0.04)', color: 'var(--ink)',
        border: '1px solid var(--line-2)',
        fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit',
        display: 'inline-flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ width: 8, height: 8, borderRadius: 999, background: sel.color }} />
        {sel.label}
        <span style={{ fontSize: 9, color: 'var(--ink-mute)', marginLeft: 2 }}>▼</span>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 20,
          minWidth: 180, padding: 6, borderRadius: 12,
          background: 'rgba(20,22,28,0.96)', backdropFilter: 'blur(12px)',
          border: '1px solid var(--line-2)', boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
        }}>
          {opts.map(o => (
            <button key={o.id} onClick={() => { setVal(o.id); setOpen(false); }} style={{
              width: '100%', padding: '8px 12px', borderRadius: 8, background: val === o.id ? 'rgba(255,255,255,0.06)' : 'transparent',
              border: 'none', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
              color: val === o.id ? '#fff' : 'var(--ink-dim)', textAlign: 'left',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: o.color }} />
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AddOneInline({ accent }) {
  return (
    <ModalShell title="Добавить аккаунт" kicker="QUICK ADD" accent={accent} width={680}>
      <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr 160px', gap: 14, alignItems: 'flex-end' }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em', marginBottom: 8 }}>ПЛАТФОРМА</div>
          <select style={{ width: '100%', padding: '11px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--line-2)', color: 'var(--ink)', fontSize: 13, fontFamily: 'inherit' }}>
            {PLATFORMS.map(p => <option key={p.id}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em', marginBottom: 8 }}>USERNAME</div>
          <input placeholder="@username" style={{ width: '100%', padding: '11px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--line-2)', color: 'var(--ink)', fontSize: 14, fontFamily: 'JetBrains Mono, monospace' }} />
        </div>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', letterSpacing: '0.2em', marginBottom: 8 }}>ПРОФИЛЬ</div>
          <select style={{ width: '100%', padding: '11px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--line-2)', color: 'var(--ink)', fontSize: 13, fontFamily: 'inherit' }}>
            <option>Без профиля</option>
            {PROFILES.map(p => <option key={p.id}>{p.label}</option>)}
          </select>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 22, justifyContent: 'flex-end' }}>
        <button style={{ padding: '10px 20px', borderRadius: 10, background: 'transparent', border: '1px solid var(--line)', color: 'var(--ink-dim)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Отмена</button>
        <button style={{ padding: '10px 24px', borderRadius: 10, background: accent, color: '#000', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Добавить</button>
      </div>
    </ModalShell>
  );
}

Object.assign(window, { ModalsScreen });
