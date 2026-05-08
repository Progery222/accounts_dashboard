// Atomic-themed visual primitives: orbits, particles, sparklines, dials, tickers.
// Uses pure SVG/CSS for crisp scaling on TVs.

const { useEffect, useRef, useState, useMemo } = React;

// ────────────────────────────────────────────────────────────
// Orbit system: a nucleus surrounded by rotating particles. Used as the
// hero metaphor — each orbit ring represents a metric (followers/views/likes/posts).
// ────────────────────────────────────────────────────────────
function OrbitSystem({ size = 720, rings, label, value, sub, color = '#6aa9ff' }) {
  const cx = size / 2, cy = size / 2;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: '100%', height: '100%', display: 'block' }}>
      <defs>
        <radialGradient id="nuc-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity="0.65" />
          <stop offset="60%" stopColor={color} stopOpacity="0.08" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </radialGradient>
        <filter id="nuc-blur"><feGaussianBlur stdDeviation="3" /></filter>
      </defs>
      {/* Nucleus glow */}
      <circle cx={cx} cy={cy} r={size * 0.18} fill="url(#nuc-glow)" />
      {/* Rings */}
      {rings.map((r, i) => {
        const rx = r.rx * (size / 720);
        const ry = r.ry * (size / 720);
        const dur = r.dur || (28 + i * 6);
        const rot = r.rot || 0;
        return (
          <g key={i} transform={`rotate(${rot} ${cx} ${cy})`}>
            <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke={r.color || color} strokeOpacity={r.opacity ?? 0.28} strokeWidth="1" strokeDasharray={r.dash || ''} />
            {/* particle */}
            <g>
              <animateTransform attributeName="transform" type="rotate" from={`0 ${cx} ${cy}`} to={`360 ${cx} ${cy}`} dur={`${dur}s`} repeatCount="indefinite" />
              <circle cx={cx + rx} cy={cy} r={r.particleR || 5} fill={r.color || color}>
                <animate attributeName="r" values={`${(r.particleR||5)*0.7};${(r.particleR||5)*1.1};${(r.particleR||5)*0.7}`} dur="2.4s" repeatCount="indefinite" />
              </circle>
              <circle cx={cx + rx} cy={cy} r={(r.particleR || 5) * 2.4} fill={r.color || color} opacity="0.18" filter="url(#nuc-blur)" />
            </g>
          </g>
        );
      })}
      {/* Nucleus core */}
      <circle cx={cx} cy={cy} r={size * 0.04} fill={color} />
      <circle cx={cx} cy={cy} r={size * 0.025} fill="#fff" opacity="0.9" />
      {/* Center label */}
      {label && (
        <g>
          <text x={cx} y={cy - size * 0.13} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontFamily="JetBrains Mono, monospace" fontSize={size * 0.022} letterSpacing="0.2em">{label}</text>
        </g>
      )}
      {value && (
        <text x={cx} y={cy + size * 0.32} textAnchor="middle" fill="#fff" fontFamily="Space Grotesk, sans-serif" fontWeight="700" fontSize={size * 0.075}>{value}</text>
      )}
      {sub && (
        <text x={cx} y={cy + size * 0.38} textAnchor="middle" fill={color} fontFamily="JetBrains Mono, monospace" fontSize={size * 0.028}>{sub}</text>
      )}
    </svg>
  );
}

// ────────────────────────────────────────────────────────────
// Sparkline — minimalist, atomic, with optional area fill.
// ────────────────────────────────────────────────────────────
function Sparkline({ data, color = '#6aa9ff', width = 240, height = 60, fill = true, dot = true, strokeWidth = 1.6 }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(1, max - min);
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => [i * stepX, height - ((v - min) / range) * (height - 6) - 3]);
  const path = points.map((p, i) => (i === 0 ? `M${p[0].toFixed(1)},${p[1].toFixed(1)}` : `L${p[0].toFixed(1)},${p[1].toFixed(1)}`)).join(' ');
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1];
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }} width={width} height={height} preserveAspectRatio="none">
      {fill && (
        <>
          <defs>
            <linearGradient id={`sparkfill-${color.replace('#','')}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#sparkfill-${color.replace('#','')})`} />
        </>
      )}
      <path d={path} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
      {dot && <circle cx={last[0]} cy={last[1]} r={3} fill={color} stroke="#0a0c12" strokeWidth="2" />}
    </svg>
  );
}

// ────────────────────────────────────────────────────────────
// Radial dial — used for percentages or composition.
// ────────────────────────────────────────────────────────────
function RadialDial({ value = 0.5, size = 120, color = '#6aa9ff', track = 'rgba(255,255,255,0.06)', strokeWidth = 8, label, sub }) {
  const r = (size - strokeWidth) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - value);
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={track} strokeWidth={strokeWidth} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={offset} style={{ transition: 'stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center' }}>
        {label && <div style={{ fontFamily: 'Space Grotesk', fontWeight: 700, fontSize: size * 0.22, color: '#fff', lineHeight: 1 }}>{label}</div>}
        {sub && <div className="mono" style={{ fontSize: size * 0.09, color: 'rgba(255,255,255,0.5)', marginTop: 4, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{sub}</div>}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// Particle field background — ambient atomic dust.
// ────────────────────────────────────────────────────────────
function ParticleField({ count = 60, color = '#6aa9ff', opacity = 0.5 }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let raf;
    const resize = () => {
      const r = canvas.getBoundingClientRect();
      canvas.width = r.width * devicePixelRatio;
      canvas.height = r.height * devicePixelRatio;
      ctx.scale(devicePixelRatio, devicePixelRatio);
    };
    resize();
    window.addEventListener('resize', resize);
    const particles = Array.from({ length: count }, () => ({
      x: Math.random(),
      y: Math.random(),
      vx: (Math.random() - 0.5) * 0.0006,
      vy: (Math.random() - 0.5) * 0.0006,
      r: Math.random() * 1.2 + 0.3,
      a: Math.random() * 0.5 + 0.15,
    }));
    const tick = () => {
      const w = canvas.width / devicePixelRatio, h = canvas.height / devicePixelRatio;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = color;
      particles.forEach(p => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > 1) p.vx *= -1;
        if (p.y < 0 || p.y > 1) p.vy *= -1;
        ctx.globalAlpha = p.a * opacity;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, p.r, 0, Math.PI * 2);
        ctx.fill();
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, [count, color, opacity]);
  return <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }} />;
}

// ────────────────────────────────────────────────────────────
// AtomicGrid — subtle technical grid background.
// ────────────────────────────────────────────────────────────
function AtomicGrid({ opacity = 0.05, size = 48 }) {
  return (
    <div style={{
      position: 'absolute', inset: 0, pointerEvents: 'none',
      backgroundImage: `linear-gradient(rgba(255,255,255,${opacity}) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,${opacity}) 1px, transparent 1px)`,
      backgroundSize: `${size}px ${size}px`,
      maskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)',
      WebkitMaskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)',
    }} />
  );
}

// ────────────────────────────────────────────────────────────
// Animated count-up
// ────────────────────────────────────────────────────────────
function useCountUp(target, duration = 1200) {
  const [v, setV] = useState(0);
  const startRef = useRef(0);
  const fromRef = useRef(0);
  useEffect(() => {
    fromRef.current = v;
    startRef.current = performance.now();
    let raf;
    const tick = (t) => {
      const p = Math.min(1, (t - startRef.current) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setV(fromRef.current + (target - fromRef.current) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line
  }, [target]);
  return v;
}

// ────────────────────────────────────────────────────────────
// PlatformGlyph — atomic-style platform pill (replaces brand icons).
// We use a neutral letter glyph + colored dot to avoid recreating brand marks.
// ────────────────────────────────────────────────────────────
function PlatformGlyph({ id, size = 18 }) {
  const meta = PLATFORM_META[id];
  if (!meta) return null;
  const letter = meta.label.charAt(0);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: 'JetBrains Mono, monospace', fontSize: size * 0.7, letterSpacing: '0.05em',
    }}>
      <span style={{
        width: size, height: size, borderRadius: 4, background: 'rgba(255,255,255,0.04)',
        border: `1px solid ${meta.color}55`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        color: meta.color, fontWeight: 700,
      }}>{letter}</span>
      {meta.label}
    </span>
  );
}

function ProfileBadge({ id, dense = false }) {
  const p = PROFILE_META[id];
  if (!p) return null;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: dense ? '2px 8px' : '4px 10px',
      borderRadius: 999, background: `${p.color}1a`, color: p.color, fontSize: 12, fontWeight: 500,
      border: `1px solid ${p.color}33`,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: p.color }} />
      {p.label}
    </span>
  );
}

// ────────────────────────────────────────────────────────────
// Stat tile with delta
// ────────────────────────────────────────────────────────────
function StatTile({ label, value, delta, color = '#6aa9ff', size = 'lg', spark }) {
  const sizes = {
    sm:  { label: 11, value: 28, delta: 13, pad: 16, lh: 1 },
    md:  { label: 12, value: 44, delta: 15, pad: 20, lh: 1 },
    lg:  { label: 13, value: 72, delta: 18, pad: 28, lh: 1 },
    xl:  { label: 14, value: 124, delta: 22, pad: 36, lh: 0.95 },
    xxl: { label: 16, value: 168, delta: 26, pad: 44, lh: 0.92 },
  };
  const s = sizes[size];
  return (
    <div style={{
      position: 'relative', padding: s.pad, borderRadius: 16,
      background: 'linear-gradient(180deg, rgba(255,255,255,0.025), rgba(255,255,255,0.01))',
      border: '1px solid var(--line)', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, ${color}, transparent)`, opacity: 0.5 }} />
      <div className="mono" style={{ fontSize: s.label, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.18em' }}>{label}</div>
      <div className="tnum" style={{ fontSize: s.value, fontWeight: 700, color: '#fff', lineHeight: s.lh, marginTop: 8, letterSpacing: '-0.02em' }}>{value}</div>
      {delta != null && (
        <div className="mono tnum" style={{ marginTop: 8, fontSize: s.delta, color: delta >= 0 ? 'var(--accent-2)' : 'var(--danger)', fontWeight: 500 }}>
          {delta >= 0 ? '▲' : '▼'} {delta >= 0 ? '+' : ''}{fmt(delta)} <span style={{ color: 'var(--ink-mute)', fontWeight: 400 }}>/24h</span>
        </div>
      )}
      {spark && <div style={{ marginTop: 12, opacity: 0.9 }}>{spark}</div>}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// Section header (used across screens)
// ────────────────────────────────────────────────────────────
function SectionHeader({ kicker, title, right }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 18 }}>
      <div>
        {kicker && <div className="mono" style={{ fontSize: 11, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.22em', marginBottom: 6 }}>{kicker}</div>}
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</div>
      </div>
      {right}
    </div>
  );
}

Object.assign(window, { OrbitSystem, Sparkline, RadialDial, ParticleField, AtomicGrid, useCountUp, PlatformGlyph, ProfileBadge, StatTile, SectionHeader });
