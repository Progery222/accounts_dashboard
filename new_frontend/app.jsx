// Root app — routes between TV broadcast and main interface screens, hosts Tweaks panel.

const { useState: useStateApp, useEffect: useEffectApp } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "tv_mood": "mission",
  "accent": "#6aa9ff",
  "accounts_view": "table",
  "start_screen": "tv"
}/*EDITMODE-END*/;

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = useStateApp(tweaks.start_screen || 'tv');

  // Auto-apply accent to CSS variables
  useEffectApp(() => {
    document.documentElement.style.setProperty('--accent', tweaks.accent);
  }, [tweaks.accent]);

  const ROUTES = [
    { id: 'tv',        label: 'TV Broadcast' },
    { id: 'accounts',  label: 'Аккаунты' },
    { id: 'analytics', label: 'Аналитика' },
    { id: 'settings',  label: 'Настройки' },
    { id: 'modals',    label: 'Модалки' },
  ];

  return (
    <>
      {route === 'tv'        && <TVScreen tweaks={tweaks} onExit={() => setRoute('accounts')} />}
      {route === 'accounts'  && <AccountsScreen tweaks={tweaks} />}
      {route === 'analytics' && <AnalyticsScreen tweaks={tweaks} />}
      {route === 'settings'  && <SettingsScreen tweaks={tweaks} onBack={() => setRoute('accounts')} />}
      {route === 'modals'    && <ModalsScreen tweaks={tweaks} />}

      {route !== 'tv' && (
        <RouteFloater route={route} setRoute={setRoute} routes={ROUTES} accent={tweaks.accent} />
      )}

      <TweaksPanel title="Tweaks">
        <TweakSection title="Старт + навигация">
          <TweakSelect label="Экран" value={route} onChange={v => setRoute(v)} options={ROUTES.map(r => ({ value: r.id, label: r.label }))} />
        </TweakSection>
        <TweakSection title="TV-режим">
          <TweakRadio label="Настроение" value={tweaks.tv_mood} onChange={v => setTweak('tv_mood', v)} options={[
            { value: 'mission', label: 'Mission' },
            { value: 'bloomberg', label: 'Bloom' },
            { value: 'calm', label: 'Calm' },
          ]} />
        </TweakSection>
        <TweakSection title="Акцент">
          <TweakColor label="Цвет" value={tweaks.accent} onChange={v => setTweak('accent', v)} options={['#6aa9ff', '#4ade80', '#f59e0b', '#ec4899', '#ffffff']} />
        </TweakSection>
        <TweakSection title="Список аккаунтов">
          <TweakRadio label="Вид" value={tweaks.accounts_view} onChange={v => setTweak('accounts_view', v)} options={[
            { value: 'table', label: 'Таблица' },
            { value: 'cards', label: 'Карточки' },
          ]} />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

function RouteFloater({ route, setRoute, routes, accent }) {
  return (
    <div style={{
      position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
      display: 'flex', gap: 4, padding: 6, borderRadius: 999,
      background: 'rgba(10,12,18,0.85)', backdropFilter: 'blur(14px)',
      border: '1px solid var(--line-2)', zIndex: 90, boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
    }}>
      {routes.map(r => (
        <button key={r.id} onClick={() => setRoute(r.id)} style={{
          padding: '9px 16px', borderRadius: 999, border: 'none', cursor: 'pointer',
          background: route === r.id ? accent : 'transparent',
          color: route === r.id ? '#000' : 'var(--ink-dim)',
          fontSize: 12, fontWeight: route === r.id ? 600 : 500, letterSpacing: '0.04em',
          fontFamily: 'inherit',
        }}>{r.label}</button>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
