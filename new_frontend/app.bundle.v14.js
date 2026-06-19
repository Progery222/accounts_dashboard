window.__NF_PRECOMPILED=true;
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// ===== tweaks-panel.jsx =====

// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;width:100%;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  noDeckControls = false,
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  // Auto-inject a rail toggle when a <deck-stage> is on the page. The
  // toggle drives the deck's per-viewer _railVisible via window message;
  // state is mirrored from the same localStorage key the deck reads so
  // the control reflects reality across reloads. The mechanism is the
  // message — authors who want custom placement can post it directly
  // and pass noDeckControls to suppress this one.
  const hasDeckStage = React.useMemo(() => typeof document !== 'undefined' && !!document.querySelector('deck-stage'), []);
  // Hide the toggle until the host has actually enabled the rail (the
  // __omelette_rail_enabled window message, posted only when the
  // omelette_deck_rail_enabled flag is on for this user). The initial read
  // covers TweaksPanel mounting after the message already arrived; the
  // listener covers the common case of mounting first.
  const [railEnabled, setRailEnabled] = React.useState(() => hasDeckStage && !!document.querySelector('deck-stage')?._railEnabled);
  React.useEffect(() => {
    if (!hasDeckStage || railEnabled) return undefined;
    const onMsg = e => {
      if (e.data && e.data.type === '__omelette_rail_enabled') setRailEnabled(true);
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [hasDeckStage, railEnabled]);
  const [railVisible, setRailVisible] = React.useState(() => {
    try {
      return localStorage.getItem('deck-stage.railVisible') !== '0';
    } catch (e) {
      return true;
    }
  });
  const toggleRail = on => {
    setRailVisible(on);
    window.postMessage({
      type: '__deck_rail_visible',
      on
    }, '*');
  };
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-noncommentable": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children, hasDeckStage && railEnabled && !noDeckControls && /*#__PURE__*/React.createElement(TweakSection, {
    label: "Deck"
  }, /*#__PURE__*/React.createElement(TweakToggle, {
    label: "Thumbnail rail",
    value: railVisible,
    onChange: toggleRail
  })))));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});

// ===== data.jsx =====
// Runtime data loaded from backend API (fallbacks stay zero-safe).
let TOTAL = {
  followers: {
    value: 0,
    delta: 0,
    yesterdayDelta: null
  },
  views: {
    value: 0,
    delta: 0,
    yesterdayDelta: null
  },
  likes: {
    value: 0,
    delta: 0,
    yesterdayDelta: null
  },
  posts: {
    value: 0,
    delta: 0,
    yesterdayDelta: null
  },
  clicks: {
    value: 0,
    delta: 0,
    yesterdayDelta: null
  },
  accounts: 0
};
let PLATFORMS = [{
  id: 'tiktok',
  label: 'TikTok',
  color: '#ff2d55',
  share: 0,
  accounts: 0
}, {
  id: 'instagram',
  label: 'Instagram',
  color: '#ec4899',
  share: 0,
  accounts: 0
}, {
  id: 'youtube',
  label: 'YouTube',
  color: '#ff4444',
  share: 0,
  accounts: 0
}, {
  id: 'x',
  label: 'X (Twitter)',
  color: '#dddddd',
  share: 0,
  accounts: 0
}, {
  id: 'threads',
  label: 'Threads',
  color: '#9aa0aa',
  share: 0,
  accounts: 0
}, {
  id: 'telegram',
  label: 'Telegram',
  color: '#26a5e4',
  share: 0,
  accounts: 0
}];
let PROFILES = [];
let ACCOUNTS = [];
let POSTS = [];
let TREND_24H = new Array(24).fill(0);
let TREND_7D = new Array(7).fill(0);
let AUTO_REFRESH_SERIES = [];
let AUTH_SESSIONS = [];
/** @type {Array<Array<{id:string,name:string,state:string,hasSession:boolean,warn:boolean,account:string|null,expires:string|null,meta:string|null,updated:string|null}>>>} */
let ALL_PLATFORMS = [];
let TV_AUTO_SCHEDULE_LABEL = '—';
let TV_AUTO_IS_RUNNING = false;
/** Период дельт аккаунтов (1 / 7 / 30 дней), из GET /api/accounts/schedule/ */
let ACCOUNT_DELTA_PERIOD_DAYS = 1;
/** Снимок списка + TOTAL для периода (префетч через GET …&delta_period_days=) */
let DELTA_PERIOD_CACHE = {
  1: null,
  7: null,
  30: null
};
const _DELTA_PERIOD_SEQUENCE = [1, 7, 30];
function _nextDeltaPeriodDays(current) {
  const cur = Number(current) || 1;
  const i = _DELTA_PERIOD_SEQUENCE.indexOf(cur);
  const idx = i >= 0 ? i : 0;
  return _DELTA_PERIOD_SEQUENCE[(idx + 1) % _DELTA_PERIOD_SEQUENCE.length];
}
function _mapAccountApiRow(a) {
  return {
    id: Number(a.id || 0),
    name: String(a.display_name || a.username || ''),
    handle: a.platform === 'rumble' ? String(a.username || '') : `@${String(a.username || '')}`,
    username: String(a.username || ''),
    avatarUrl: _accountAvatarSrc(a),
    platform: String(a.platform || ''),
    profile: a.profile_id != null ? String(a.profile_id) : 'none',
    audienceMembers: Number(a.audience_members_count ?? 0),
    followers: Number(a.follower_count || 0),
    dFollowers: Number(a.follower_delta ?? 0),
    views: Number(a.view_count || 0),
    dViews: Number(a.view_delta || 0),
    likes: Number(a.like_count || 0),
    dLikes: String(a.platform || '').toLowerCase() === 'facebook' && !Number(a.like_count || 0) ? 0 : Number(a.like_delta ?? 0),
    posts: Number(a.post_count || 0),
    dPosts: Number(a.post_delta || 0),
    clicks: Number(a.link_click_count || 0),
    dClicks: Number(a.link_click_delta ?? 0),
    unavailable: !!a.profile_unavailable,
    unavailableReason: String(a.profile_unavailable_reason || a.unavailable_reason || ''),
    isPlatformHidden: !!a.is_platform_hidden,
    isProfileHidden: !!a.is_profile_hidden,
    updated: _ruShortDate(a.updated_at),
    updatedTs: (() => {
      const t = Date.parse(String(a.updated_at || ''));
      return Number.isFinite(t) ? t : 0;
    })()
  };
}

/** Подпись на TV «TOP MOVERS»: Facebook — человекочитаемое имя и @username/id рядом. */
function _tvBroadcastAccountTitle(a) {
  if (!a) return '';
  const plat = String(a.platform || '').toLowerCase();
  const u = String(a.username || '').trim();
  const n = String(a.name || '').trim();
  const handle = String(a.handle || (u ? `@${u}` : ''));
  if (plat !== 'facebook') return handle;
  const hasHumanName = n && !/^\d{6,24}$/.test(n);
  const nameDiffersFromUser = hasHumanName && n.toLowerCase() !== u.toLowerCase();
  if (nameDiffersFromUser) return `${n} ${handle}`;
  return handle;
}
function _totalFromSummary(summary) {
  return {
    followers: {
      value: Number(summary.follower_count || 0),
      delta: Number(summary.follower_delta || 0),
      yesterdayDelta: _parseSummaryYesterdayDelta(summary.yesterday_follower_delta)
    },
    views: {
      value: Number(summary.view_count || 0),
      delta: Number(summary.view_delta || 0),
      yesterdayDelta: _parseSummaryYesterdayDelta(summary.yesterday_view_delta)
    },
    likes: {
      value: Number(summary.like_count || 0),
      delta: Number(summary.like_delta || 0),
      yesterdayDelta: _parseSummaryYesterdayDelta(summary.yesterday_like_delta)
    },
    posts: {
      value: Number(summary.post_count || 0),
      delta: Number(summary.post_delta || 0),
      yesterdayDelta: _parseSummaryYesterdayDelta(summary.yesterday_post_delta)
    },
    clicks: {
      value: Number(summary.link_click_count || 0),
      delta: Number(summary.link_click_delta || 0),
      yesterdayDelta: null
    },
    accounts: Number(summary.account_count || 0)
  };
}
function _platformsFromSummary(summary) {
  const byPlatform = Array.isArray(summary.by_platform) ? summary.by_platform : [];
  const totalAcc = Math.max(1, Number(summary.account_count || 0));
  return byPlatform.map(p => ({
    id: String(p.platform || ''),
    label: String(p.platform_label || p.platform || ''),
    color: PLATFORM_COLORS[String(p.platform || '')] || '#9ca3af',
    share: Math.max(0, Number(p.account_count || 0) / totalAcc),
    accounts: Number(p.account_count || 0)
  }));
}
function _applyDeltaSnapshotToGlobals(snap) {
  if (!snap || !Array.isArray(snap.accounts) || !snap.total) return false;
  ACCOUNTS = snap.accounts.map(x => ({
    ...x
  }));
  TOTAL = JSON.parse(JSON.stringify(snap.total));
  if (Array.isArray(snap.platforms)) PLATFORMS = snap.platforms.map(x => ({
    ...x
  }));
  const byProfileFromAccounts = new Map();
  for (const acc of ACCOUNTS) {
    const key = String(acc.profile || 'none');
    byProfileFromAccounts.set(key, (byProfileFromAccounts.get(key) || 0) + 1);
  }
  PROFILES = PROFILES.map(p => ({
    ...p,
    accounts: Number(byProfileFromAccounts.get(String(p.id)) || 0)
  }));
  TREND_24H = _buildAscendingTrend(TOTAL.views.value, TOTAL.views.delta, 24);
  TREND_7D = _buildAscendingTrend(TOTAL.views.value, TOTAL.views.delta * 3, 7);
  return true;
}
function _buildDeltaSnapshot(summary, accountsRaw) {
  if (!summary || !Array.isArray(accountsRaw)) return null;
  return {
    accounts: accountsRaw.map(_mapAccountApiRow),
    total: _totalFromSummary(summary),
    platforms: _platformsFromSummary(summary)
  };
}
function _storeDeltaCacheForPeriod(period, snapshot) {
  if (![1, 7, 30].includes(period) || !snapshot) return;
  DELTA_PERIOD_CACHE[period] = {
    accounts: snapshot.accounts.map(x => ({
      ...x
    })),
    total: JSON.parse(JSON.stringify(snapshot.total)),
    platforms: snapshot.platforms.map(x => ({
      ...x
    }))
  };
}
async function _prefetchDeltaPeriodInBackground(period) {
  if (![1, 7, 30].includes(period) || DELTA_PERIOD_CACHE[period]) return;
  try {
    const [sr, ar] = await Promise.all([_fetchJsonSoft(`/api/accounts/summary/?include_hidden=1&delta_period_days=${period}`), _fetchJsonSoft(`/api/accounts/?include_hidden=1&delta_period_days=${period}`)]);
    if (!sr.ok || !ar.ok || !Array.isArray(ar.data) || !sr.data) return;
    const snap = _buildDeltaSnapshot(sr.data, ar.data);
    if (snap) _storeDeltaCacheForPeriod(period, snap);
  } catch (_) {/* префетч не критичен */}
}
function _scheduleDeltaPrefetchExcept(excludePeriod) {
  setTimeout(() => {
    for (const p of _DELTA_PERIOD_SEQUENCE) {
      if (p === excludePeriod) continue;
      void _prefetchDeltaPeriodInBackground(p);
    }
  }, 100);
}
let LOAD_STATE = {
  hasError: false,
  errorMessage: ''
};
function _buildAscendingTrend(total, delta, points) {
  const safePoints = Math.max(2, Number(points || 24));
  const safeTotal = Math.max(0, Number(total || 0));
  const safeDelta = Math.max(0, Number(delta || 0));
  const start = Math.max(0, safeTotal - safeDelta);
  const amplitude = Math.max(1, safeDelta || Math.max(1, safeTotal * 0.06));
  const out = [];
  for (let i = 0; i < safePoints; i += 1) {
    const t = i / (safePoints - 1);
    // Ease-out growth with a tiny deterministic wave to avoid perfectly straight lines.
    const eased = 1 - Math.pow(1 - t, 1.5);
    const wave = Math.sin(i * 0.55) * amplitude * 0.035;
    const value = start + amplitude * eased + wave;
    out.push(Math.max(0, Math.round(value)));
  }

  // Ensure strictly non-decreasing look for chart segments.
  for (let i = 1; i < out.length; i += 1) {
    if (out[i] < out[i - 1]) out[i] = out[i - 1];
  }
  return out;
}
function _buildTrendFromSeries(points, desired = 24) {
  const n = Math.max(2, Number(desired || 24));
  const arr = Array.isArray(points) ? points : [];
  const values = arr.map(p => Number(p?.view_count_total || 0)).filter(v => Number.isFinite(v) && v >= 0);
  if (!values.length) return null;
  if (values.length === n) return values;
  if (values.length === 1) return new Array(n).fill(values[0]);
  const out = [];
  const lastIdx = values.length - 1;
  for (let i = 0; i < n; i += 1) {
    const t = i / (n - 1) * lastIdx;
    const left = Math.floor(t);
    const right = Math.min(lastIdx, Math.ceil(t));
    const alpha = t - left;
    const v = values[left] + (values[right] - values[left]) * alpha;
    out.push(Math.max(0, Math.round(v)));
  }
  return out;
}
function _seriesValueSpread(values) {
  const arr = (Array.isArray(values) ? values : []).map(v => Number(v)).filter(v => Number.isFinite(v));
  if (arr.length < 2) return 0;
  return Math.max(...arr) - Math.min(...arr);
}

/** Плато в данных: после импорта CSV totals/дельты часто одинаковые — график рисуется «прямой». */
function _isFlatSeriesValues(values) {
  const max = Math.max(0, ...(Array.isArray(values) ? values : []).map(v => Number(v || 0)));
  const spread = _seriesValueSpread(values);
  return spread < Math.max(800, max * 0.003);
}
const CHART_HOUR_MS = 60 * 60 * 1000;
function _hourSlotStartLocal(ts) {
  const d = new Date(Number(ts) || Date.now());
  d.setMinutes(0, 0, 0);
  return d.getTime();
}

/** 1 точка = 1 час (последняя запись в слоте; пустые часы — hold последнего total). */
function _aggregateSeriesByHour(series, windowEndTs = Date.now(), hours = 24) {
  const windowEnd = Number(windowEndTs) || Date.now();
  const endHour = _hourSlotStartLocal(windowEnd);
  const startHour = endHour - (Math.max(1, hours) - 1) * CHART_HOUR_MS;
  const src = (Array.isArray(series) ? series : []).map(p => ({
    ...p,
    _ts: Date.parse(String(p?.measured_at || ''))
  })).filter(p => Number.isFinite(p._ts) && p._ts <= windowEnd + 60000).sort((a, b) => a._ts - b._ts);
  const buckets = new Map();
  for (const p of src) {
    if (String(p?.source || '') === 'anchor') continue;
    const key = _hourSlotStartLocal(p._ts);
    const prev = buckets.get(key);
    if (!prev || p._ts >= prev._ts) buckets.set(key, p);
  }
  let lastTotal = null;
  let lastDayStart = 0;
  let lastPlatforms = {};
  const before = src.filter(p => p._ts < startHour);
  if (before.length) {
    const b = before[before.length - 1];
    lastTotal = Number(b.view_count_total || 0);
    lastDayStart = Number(b.view_delta_from_day_start || 0);
    lastPlatforms = b.platform_deltas && typeof b.platform_deltas === 'object' ? b.platform_deltas : {};
  }
  const anchor = src.find(p => String(p?.source || '') === 'anchor');
  if (anchor && lastTotal == null) {
    lastTotal = Number(anchor.view_count_total || 0);
  }
  const slots = [];
  for (let i = 0; i < hours; i += 1) {
    const slotStart = startHour + i * CHART_HOUR_MS;
    const slotEnd = slotStart + CHART_HOUR_MS - 1;
    const hit = buckets.get(slotStart);
    if (hit) {
      lastTotal = Number(hit.view_count_total || lastTotal || 0);
      lastDayStart = Number(hit.view_delta_from_day_start || lastDayStart);
      lastPlatforms = hit.platform_deltas && typeof hit.platform_deltas === 'object' ? hit.platform_deltas : lastPlatforms;
    }
    if (lastTotal == null) continue;
    const hourLabel = new Date(slotStart).toLocaleTimeString('ru-RU', {
      hour: '2-digit',
      minute: '2-digit'
    });
    slots.push({
      id: hit?.id || 0,
      measured_at: new Date(slotEnd).toISOString(),
      slot_label: hourLabel,
      source: hit ? hit.source || 'hourly' : 'hourly_hold',
      view_count_total: lastTotal,
      view_delta_from_prev_point: 0,
      view_delta_from_day_start: lastDayStart,
      platform_deltas: {
        ...lastPlatforms
      }
    });
  }
  for (let i = 1; i < slots.length; i += 1) {
    const prev = Number(slots[i - 1].view_count_total || 0);
    const cur = Number(slots[i].view_count_total || 0);
    slots[i].view_delta_from_prev_point = Math.max(0, cur - prev);
  }
  if (slots.length) slots[0].view_delta_from_prev_point = Math.max(0, Number(slots[0].view_delta_from_prev_point || 0));
  return slots;
}

/** Строго неубывающая серия (без просадок на графике). */
function _smoothMonotonicUpward(values) {
  const out = [];
  let prev = 0;
  for (const v of Array.isArray(values) ? values : []) {
    const n = Math.max(prev, Math.max(0, Number(v) || 0));
    out.push(n);
    prev = n;
  }
  return out;
}

/** Реальные totals + кумулятив дельт; только убираем просадки вниз. */
function _displayTotalsForChart(series, liveViewsTotal, dayDeltaViews) {
  const src = Array.isArray(series) ? series : [];
  if (!src.length) return null;
  const totals = src.map(p => Number(p?.view_count_total || 0));
  const end = Math.max(Number(liveViewsTotal || 0), ...totals, totals[totals.length - 1] || 0);
  const firstReal = src.find(p => String(p?.source || '') !== 'anchor') || src[0];
  const dayStartTotal = Number(firstReal?.view_count_total || 0) - Number(firstReal?.view_delta_from_day_start || 0);
  const start = Math.max(0, Math.min(end, Number.isFinite(dayStartTotal) ? dayStartTotal : end - Math.max(0, Number(dayDeltaViews || 0))));
  const fromTotals = _smoothMonotonicUpward(totals);
  if (!_isFlatSeriesValues(fromTotals)) {
    fromTotals[fromTotals.length - 1] = Math.max(fromTotals[fromTotals.length - 1], end);
    return fromTotals;
  }
  let cum = start;
  const fromDeltas = src.map(p => {
    if (String(p?.source || '') === 'anchor') return start;
    const d = Math.max(0, Number(p?.view_delta_from_prev_point || 0));
    cum += d;
    return cum;
  });
  fromDeltas[fromDeltas.length - 1] = Math.max(fromDeltas[fromDeltas.length - 1], end);
  return _smoothMonotonicUpward(fromDeltas);
}

/** Узлы для отрисовки: скачки сохраняем, лишние «плато» сжимаем. */
function _chartKnotsFromPoints(points, maxKnots = 56) {
  const sorted = (Array.isArray(points) ? points : []).filter(p => Number.isFinite(p?.ts) && Number.isFinite(p?.value)).sort((a, b) => a.ts - b.ts);
  if (sorted.length <= maxKnots) return sorted;
  const key = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const p = sorted[i];
    const prev = sorted[i - 1];
    const next = sorted[i + 1];
    const valChanged = !prev || p.value !== prev.value;
    const nextChange = next && p.value !== next.value;
    const isEdge = i === 0 || i === sorted.length - 1;
    if (isEdge || valChanged || nextChange) key.push(p);
  }
  if (key.length <= maxKnots) return key;
  const stride = Math.ceil(key.length / maxKnots);
  const out = key.filter((_, i) => i === 0 || i === key.length - 1 || i % stride === 0);
  if (out[out.length - 1] !== key[key.length - 1]) out.push(key[key.length - 1]);
  return out;
}

/** Лёгкая интерполяция между узлами (линейная, без «искусственного» ease). */
function _interpolateChartKnots(knots, samples = 28) {
  const src = Array.isArray(knots) ? knots : [];
  if (src.length < 2) return src;
  if (src.length >= samples) return src;
  const t0 = src[0].ts;
  const t1 = src[src.length - 1].ts;
  const n = Math.max(2, Number(samples) || 28);
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const t = t0 + (t1 - t0) * i / (n - 1);
    let y = src[src.length - 1].value;
    for (let j = 0; j < src.length - 1; j += 1) {
      const a = src[j];
      const b = src[j + 1];
      if (t <= b.ts) {
        const span = Math.max(1, b.ts - a.ts);
        const u = (t - a.ts) / span;
        y = a.value + (b.value - a.value) * u;
        break;
      }
    }
    out.push({
      ts: t,
      value: y
    });
  }
  return _smoothMonotonicUpward(out.map(p => p.value)).map((value, i) => ({
    ts: out[i].ts,
    value
  }));
}

/** SVG: лёгкое скругление углов, форма близка к реальным скачкам. */
function _svgSmoothCurvePath(xyPoints) {
  const pts = Array.isArray(xyPoints) ? xyPoints : [];
  if (pts.length < 2) return '';
  if (pts.length === 2) {
    return `M${pts[0][0]},${pts[0][1]} L${pts[1][0]},${pts[1][1]}`;
  }
  const tension = 0.12;
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i += 1) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6 * tension;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6 * tension;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6 * tension;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6 * tension;
    d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}
function _normalizeSparkData(arr) {
  const src = Array.isArray(arr) ? arr : [];
  if (src.length === 0) return [0, 0];
  const maxAbs = Math.max(1, ...src.map(v => Math.abs(Number(v || 0))));
  const out = src.map(v => Number(v || 0) / maxAbs);
  if (out.length < 2) out.unshift(0);
  return out;
}
function _platformPulseFromSeries(series, platformId) {
  const id = String(platformId || '').toLowerCase();
  const src = Array.isArray(series) ? series : [];
  if (!id || src.length === 0) return {
    data: null,
    totalDelta: 0,
    hasVariation: false
  };
  let cumulative = 0;
  const cumSeries = src.map(p => {
    const m = p && typeof p.platform_deltas === 'object' ? p.platform_deltas : null;
    const delta = m ? Math.max(0, Number(m[id] || 0)) : 0;
    cumulative += Number.isFinite(delta) ? delta : 0;
    return cumulative;
  });
  const smooth = _smoothMonotonicUpward(cumSeries);
  if (smooth.length < 2) smooth.unshift(0);
  const spread = _seriesValueSpread(smooth);
  return {
    data: smooth,
    totalDelta: smooth[smooth.length - 1] || 0,
    hasVariation: Math.abs(spread) >= 1
  };
}
function fmt(n) {
  if (n == null) return '—';
  if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1).replace('.0', '') + 'M';
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1).replace('.0', '') + 'K';
  return String(n);
}
function fmtSign(n) {
  if (n == null) return '';
  return (n > 0 ? '+' : '') + fmt(n);
}
const PLATFORM_COLORS = {
  tiktok: '#ff2d55',
  instagram: '#ec4899',
  youtube: '#ff4444',
  x: '#dddddd',
  threads: '#9aa0aa',
  telegram: '#26a5e4',
  facebook: '#1877F2',
  rumble: '#85c742',
  reddit: '#ff5700'
};
const PROFILE_PALETTE = ['#4ade80', '#fb923c', '#ec4899', '#6aa9ff', '#f59e0b', '#22d3ee', '#a78bfa'];
let PLATFORM_META = {};
let PROFILE_META = {};
function recomputeMeta() {
  PLATFORM_META = Object.fromEntries(PLATFORMS.map(p => [p.id, p]));
  PROFILE_META = Object.fromEntries(PROFILES.map(p => [p.id, p]));
  Object.assign(window, {
    TOTAL,
    PLATFORMS,
    PROFILES,
    ACCOUNTS,
    POSTS,
    TREND_24H,
    TREND_7D,
    AUTO_REFRESH_SERIES,
    AUTH_SESSIONS,
    ALL_PLATFORMS,
    LOAD_STATE,
    fmt,
    fmtSign,
    PLATFORM_META,
    PROFILE_META
  });
}
function _ruShortDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).replace(',', '');
}
function _daysUntil(iso) {
  if (!iso) return null;
  const d = new Date(String(iso).replace(' UTC', 'Z'));
  if (Number.isNaN(d.getTime())) return null;
  return Math.round((d.getTime() - Date.now()) / 86400000);
}
function _expiryBadge(days) {
  if (days == null) return null;
  if (days <= 0) return 'истекло';
  if (days === 1) return '1 день';
  if (days < 30) return `${days} дн.`;
  return `${Math.round(days / 30)} мес.`;
}
function _buildTvAutoScheduleLabel(sched) {
  if (!sched || typeof sched !== 'object') return '—';
  if (!sched.enabled) return 'OFF';
  const mode = String(sched.mode || 'times');
  if (mode === 'interval') {
    const h = Number(sched.interval_hours || 0);
    return h > 0 ? `КАЖДЫЕ ${h}Ч` : 'INTERVAL';
  }
  const times = Array.isArray(sched.times) ? sched.times.map(t => String(t).trim()).filter(t => /^\d{2}:\d{2}$/.test(t)).sort() : [];
  return times.length > 0 ? times.join(' / ') : '—';
}

/** Календарная дата Europe/Moscow (YYYY-MM-DD) — смена дня для фонового обновления summary / вчерашних дельт. */
function _mskCalendarDateKey(d = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(d);
}

/** Доп. текст к ошибке fetch, если умер ephemeral-туннель Cloudflare. */
function _apiTunnelDeadHint(err) {
  const m = String(err instanceof Error ? err.message : err || '');
  if (/\b501\b/i.test(m) && /5174/i.test(m)) {
    return `${m}\n\n` + 'Порт 5174 — только статика (run_server.py), POST на /api не поддерживается. ' + 'Запустите Django на http://127.0.0.1:8000 — запросы к API пойдут туда автоматически.';
  }
  if (!/trycloudflare\.com/i.test(m)) return m;
  if (!/\b530\b|\b502\b|\b503\b|\b504\b/i.test(m)) return m;
  return `${m}\n\n` + 'Туннель trycloudflare больше не смотрит на Django (или бэкенд выключен). ' + 'Варианты: снова поднять cloudflared к `http://127.0.0.1:8000`, открыть интерфейс с `http://127.0.0.1:5174` ' + 'и очистить в localStorage ключ `new_frontend_api_base`, либо записать туда актуальный URL API.';
}

/** Текст `detail` из JSON-ответа DRF при ошибке (иначе пользователь видит только «HTTP xxx»). */
function _formatApiDetailField(detail) {
  if (detail == null) return '';
  if (typeof detail === 'string') return detail.trim();
  if (Array.isArray(detail)) {
    return detail.map(x => x && typeof x === 'object' ? JSON.stringify(x) : String(x)).filter(Boolean).join('; ');
  }
  if (typeof detail === 'object') return JSON.stringify(detail);
  return String(detail);
}
function _formatApiErrorBody(body) {
  if (!body || typeof body !== 'object') return '';
  if (body.detail != null) {
    const d = _formatApiDetailField(body.detail);
    if (d) return d;
  }
  if (Array.isArray(body.non_field_errors) && body.non_field_errors.length) {
    return body.non_field_errors.map(x => String(x)).filter(Boolean).join('; ');
  }
  const parts = [];
  for (const [key, val] of Object.entries(body)) {
    if (key === 'detail') continue;
    const t = _formatApiDetailField(val);
    if (t) parts.push(`${key}: ${t}`);
  }
  return parts.join('; ');
}
async function _errorMessageFromResponse(res, fallback) {
  const ct = (res.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('application/json')) return fallback;
  try {
    const body = await res.json();
    const d = _formatApiErrorBody(body);
    if (d) return `${d} (HTTP ${res.status})`;
  } catch (_) {}
  return fallback;
}
async function _fetchJson(url) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        cache: 'no-store'
      });
      if (!res.ok) {
        const fb = `HTTP ${res.status} for ${base}${url}`;
        throw new Error(await _errorMessageFromResponse(res, fb));
      }
      return res.json();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to fetch ${url}`)));
}

/** Успех/ошибка без «тихого» [] / null, чтобы отличить сбой сети от пустого ответа API. */
async function _fetchJsonSoft(url) {
  try {
    const data = await _fetchJson(url);
    return {
      ok: true,
      data
    };
  } catch (error) {
    return {
      ok: false,
      error
    };
  }
}
async function _postJson(url, payload) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload ?? {})
      });
      if (!res.ok) {
        const fb = `HTTP ${res.status} for ${base}${url}`;
        throw new Error(await _errorMessageFromResponse(res, fb));
      }
      return res.status === 204 ? null : res.json();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to post ${url}`)));
}
async function _patchJson(url, payload) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload ?? {})
      });
      if (!res.ok) {
        const fb = `HTTP ${res.status} for ${base}${url}`;
        throw new Error(await _errorMessageFromResponse(res, fb));
      }
      return res.status === 204 ? null : res.json();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to patch ${url}`)));
}
async function _delete(url) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        method: 'DELETE'
      });
      if (!res.ok) {
        const fb = `HTTP ${res.status} for ${base}${url}`;
        throw new Error(await _errorMessageFromResponse(res, fb));
      }
      return;
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to delete ${url}`)));
}

/** GET → Blob: перебирает базы API (как _fetchJson), если same-origin не проксирует /api/. */
async function _fetchBlobWithApiBases(url) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        cache: 'no-store'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${base}${url}`);
      return await res.blob();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to fetch blob ${url}`)));
}

/** POST multipart → JSON: новый FormData на каждую попытку (файл нельзя читать повторно). */
async function _postFormDataJsonWithApiBases(url, file, fieldName = 'file') {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const fd = new FormData();
      fd.append(fieldName, file);
      const res = await fetch(`${base}${url}`, {
        method: 'POST',
        body: fd
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (j && j.detail) msg = String(j.detail);
        } catch (_) {/* ignore */}
        throw new Error(msg);
      }
      return await res.json();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to post ${url}`)));
}

/** POST → Blob (например refresh_all?download_csv=1). */
async function _postBlobWithApiBases(url, init) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        method: 'POST',
        ...(init || {})
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${base}${url}`);
      return await res.blob();
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to post ${url}`)));
}

/** POST multipart → JSON с прогрессом загрузки (XHR). onPhase: upload | processing. */
function _postFormDataJsonWithUploadProgress(url, file, fieldName, callbacks) {
  const onUploadPercent = callbacks && callbacks.onUploadPercent;
  const onPhase = callbacks && callbacks.onPhase;
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  const tryBase = baseIndex => new Promise((resolve, reject) => {
    if (baseIndex >= candidates.length) {
      reject(lastErr || new Error(`Failed to post ${url}`));
      return;
    }
    const base = candidates[baseIndex];
    const fd = new FormData();
    fd.append(fieldName, file);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${base}${url}`);
    xhr.upload.addEventListener('progress', e => {
      if (!e.lengthComputable || !onUploadPercent) return;
      const pct = Math.min(88, Math.max(0, Math.round(e.loaded / e.total * 88)));
      onUploadPercent(pct, e.loaded, e.total);
    });
    xhr.upload.addEventListener('load', () => {
      if (onPhase) onPhase('processing');
      if (onUploadPercent) onUploadPercent(92, file.size, file.size);
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          if (onUploadPercent) onUploadPercent(100, file.size, file.size);
          resolve(JSON.parse(xhr.responseText || '{}'));
        } catch (parseErr) {
          reject(parseErr);
        }
        return;
      }
      let msg = `HTTP ${xhr.status}`;
      try {
        const j = JSON.parse(xhr.responseText || '{}');
        if (j && j.detail) msg = String(j.detail);
      } catch (_) {/* ignore */}
      lastErr = new Error(msg);
      tryBase(baseIndex + 1).then(resolve).catch(reject);
    });
    xhr.addEventListener('error', () => {
      lastErr = new Error(`Network error for ${base}${url}`);
      tryBase(baseIndex + 1).then(resolve).catch(reject);
    });
    xhr.addEventListener('abort', () => {
      reject(new Error('Загрузка отменена'));
    });
    if (onPhase) onPhase('upload');
    if (onUploadPercent) onUploadPercent(0, 0, file.size || 0);
    xhr.send(fd);
  });
  return tryBase(0).catch(err => {
    throw new Error(_apiTunnelDeadHint(err));
  });
}
function _formatImportSummaryMessage(summary) {
  const parts = [];
  if (summary.accounts_created) parts.push(`аккаунтов создано: ${summary.accounts_created}`);
  if (summary.accounts_updated) parts.push(`аккаунтов обновлено: ${summary.accounts_updated}`);
  if (summary.posts_created) parts.push(`постов создано: ${summary.posts_created}`);
  if (summary.posts_updated) parts.push(`постов обновлено: ${summary.posts_updated}`);
  if (summary.account_snapshots_upserted) parts.push(`снапшотов аккаунтов: ${summary.account_snapshots_upserted}`);
  if (summary.post_snapshots_upserted) parts.push(`снапшотов постов: ${summary.post_snapshots_upserted}`);
  if (summary.auto_refresh_points_imported) {
    parts.push(`точек графика Live: ${summary.auto_refresh_points_imported}`);
  }
  if (summary.auto_refresh_chart_times_remapped) {
    parts.push('время точек графика сдвинуто в последние 24 ч');
  }
  const errs = Array.isArray(summary.errors) ? summary.errors : [];
  let msg = parts.length ? parts.join('\n') : 'Данные обработаны (без изменений счётчиков).';
  if (errs.length) {
    const errLines = errs.slice(0, 20).map(e => `${e.section || '—'}, строка ${e.row}: ${e.message}`);
    if (errs.length > 20) errLines.push(`…и ещё ${errs.length - 20} ошибок`);
    msg += `\n\nОшибки (${errs.length}):\n${errLines.join('\n')}`;
  }
  return {
    msg,
    errs,
    parts
  };
}
function _isLocalHostHostName(hostname) {
  const h = String(hostname || '').toLowerCase();
  return h === 'localhost' || h === '127.0.0.1' || h === '::1';
}

/** ``run_server.py`` new_frontend — только статика, без /api; POST на этот origin → HTTP 501. */
function _isLikelyNewFrontendStaticServerOrigin() {
  try {
    const u = new URL(window.location.href);
    if (!_isLocalHostHostName(u.hostname)) return false;
    const p = u.port || (u.protocol === 'https:' ? '443' : '80');
    return String(p) === '5174';
  } catch (_) {
    return false;
  }
}
function _isPrivateLoopbackBase(base) {
  try {
    const u = new URL(base);
    return _isLocalHostHostName(u.hostname);
  } catch (_) {
    return false;
  }
}

/** Префикс при встраивании в Atome Studio (nginx /accounts-stats/ → dashboard). */
function _mountedPathPrefix() {
  try {
    const p = window.location.pathname || '';
    if (p === '/accounts-stats' || p.startsWith('/accounts-stats/')) return '/accounts-stats';
  } catch (_) {}
  return '';
}
function _isEmbedMode() {
  try {
    return new URLSearchParams(window.location.search).get('embed') === '1';
  } catch (_) {
    return false;
  }
}

/** Корневой контейнер экрана: в embed — 100% iframe, без лишней полосы под 100vh. */
function _pageShellStyle(extra) {
  const base = {
    display: 'flex',
    flexDirection: 'column'
  };
  if (_isEmbedMode()) {
    return {
      ...base,
      minHeight: '100%',
      height: '100%',
      flex: 1,
      minWidth: 0,
      ...extra
    };
  }
  return {
    ...base,
    minHeight: '100vh',
    ...extra
  };
}

/** В iframe (Atome Studio) — контент на всю ширину, без max-width 1600px по центру. */
function _embedShellStyle(isMobile, extra) {
  if (_isEmbedMode()) {
    return {
      flex: 1,
      width: '100%',
      maxWidth: 'none',
      margin: 0,
      padding: isMobile ? '0 0 64px' : '0 0 64px',
      boxSizing: 'border-box',
      ...extra
    };
  }
  return {
    flex: 1,
    padding: isMobile ? '12px 10px 132px' : '28px 36px 60px',
    maxWidth: 1600,
    width: '100%',
    margin: '0 auto',
    ...extra
  };
}
function _apiBaseCandidates() {
  const storedBase = (window.localStorage.getItem('new_frontend_api_base') || '').trim().replace(/\/$/, '');
  const host = window.location.hostname || '';
  const isLocalPage = _isLocalHostHostName(host);
  const pathPrefix = _mountedPathPrefix();
  const sameOrigin = window.location.origin.replace(/\/$/, '') + pathPrefix;
  const storedTunnel = /trycloudflare\.com/i.test(storedBase);
  /** @type {string[]} */
  const out = [];
  const add = b => {
    const v = String(b || '').trim().replace(/\/$/, '');
    if (!v || out.includes(v)) return;
    out.push(v);
  };

  // Только dev static server (:5174): там нет /api. На :9080 / :8080 (nginx+docker) API на same-origin.
  if (isLocalPage) {
    try {
      const pagePort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
      if (String(pagePort) === '5174') {
        add('http://127.0.0.1:8000');
        add('http://localhost:8000');
      }
    } catch (_) {
      /* ignore */
    }
  }

  // Same-origin: при общем туннеле с бэкендом сюда попадёт рабочий API.
  // Не добавляем http://127.0.0.1:5174 (new_frontend/run_server.py): там только SimpleHTTPRequestHandler,
  // пути /api/... не проксируются — POST возвращает HTTP 501.
  if (!_isLikelyNewFrontendStaticServerOrigin()) {
    add(sameOrigin);
  }
  if (storedBase) {
    if (isLocalPage && storedTunnel) {
      // Не добавляем старый trycloudflare при локальной разработке — он почти всегда 530.
    } else if (isLocalPage || !_isPrivateLoopbackBase(storedBase)) {
      add(storedBase);
    }
  }

  return out;
}
function _apiBasePrimary() {
  const candidates = _apiBaseCandidates();
  if (candidates.length) return candidates[0];
  if (_isLikelyNewFrontendStaticServerOrigin()) return 'http://127.0.0.1:8000';
  return window.location.origin.replace(/\/$/, '');
}
async function uiAlert(message, title = 'Уведомление') {
  if (window.__nf_ui && typeof window.__nf_ui.alert === 'function') {
    return window.__nf_ui.alert(String(message || ''), String(title || 'Уведомление'));
  }
  window.alert(String(message || ''));
}
async function uiConfirm(message, title = 'Подтверждение') {
  if (window.__nf_ui && typeof window.__nf_ui.confirm === 'function') {
    return window.__nf_ui.confirm(String(message || ''), String(title || 'Подтверждение'));
  }
  return window.confirm(String(message || ''));
}
async function uiPrompt(label, initialValue = '', title = 'Ввод') {
  if (window.__nf_ui && typeof window.__nf_ui.prompt === 'function') {
    return window.__nf_ui.prompt(String(label || ''), String(initialValue || ''), String(title || 'Ввод'));
  }
  return window.prompt(String(label || ''), String(initialValue || ''));
}
function _hasDelta(v) {
  if (v === null || v === undefined) return false;
  const n = Number(v);
  return Number.isFinite(n) && Math.abs(n) >= 1e-6;
}

/** Подпись дельты для UI; null — не показывать (в т.ч. 0 и «+0»). */
function _deltaLabel(v) {
  if (!_hasDelta(v)) return null;
  const n = Number(v);
  const text = (n > 0 ? '+' : '') + fmt(n);
  if (text === '0' || text === '+0' || text === '-0') return null;
  return text;
}
function _deltaColor(v) {
  return Number(v || 0) < 0 ? '#f87171' : '#4ade80';
}
function _deltaGlow(v) {
  return Number(v || 0) < 0 ? '0 0 10px rgba(248,113,113,0.35)' : '0 0 10px rgba(74,222,128,0.28)';
}
function _pickAvatarUrl(obj) {
  if (!obj || typeof obj !== 'object') return '';
  const candidates = [obj.avatar_url, obj.avatar, obj.profile_image_url, obj.profile_picture_url, obj.picture_url, obj.image_url, obj.photo_url];
  for (const c of candidates) {
    const v = String(c || '').trim();
    if (v) return v;
  }
  return '';
}
/** Аватар через Django-прокси: Referer, протухшие CDN, TikTok без URL в БД. */
function _accountAvatarSrc(a) {
  const id = Number(a?.id || 0);
  if (id > 0) {
    const base = (_apiBasePrimary() || '').replace(/\/$/, '');
    if (base) return `${base}/api/accounts/${id}/avatar/`;
  }
  return _pickAvatarUrl(a);
}
function _postShowsThumbnail(p) {
  if (p?.thumbnail_missing) return false;
  const id = Number(p?.id || 0);
  return id > 0 || !!(String(p?.thumbnail_url || '').trim());
}
function _postThumbnailSrc(p) {
  const id = Number(p?.id || 0);
  if (id > 0 && !p?.thumbnail_missing) {
    const base = (_apiBasePrimary() || '').replace(/\/$/, '');
    if (base) return `${base}/api/posts/${id}/thumbnail/`;
  }
  return String(p?.thumbnail_url || '').trim();
}
function _toSortableNumber(v) {
  if (v == null) return 0;
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
  const raw = String(v).trim().toLowerCase().replace(/\s+/g, '').replace(',', '.');
  if (!raw) return 0;
  const m = raw.match(/^(-?\d+(?:\.\d+)?)([kmb])?$/i);
  if (m) {
    const base = Number(m[1] || 0);
    if (!Number.isFinite(base)) return 0;
    const suffix = String(m[2] || '').toLowerCase();
    const mult = suffix === 'b' ? 1e9 : suffix === 'm' ? 1e6 : suffix === 'k' ? 1e3 : 1;
    return base * mult;
  }
  const digitsOnly = raw.replace(/[^\d.-]/g, '');
  const parsed = Number(digitsOnly);
  return Number.isFinite(parsed) ? parsed : 0;
}
function _normUser(username) {
  return String(username || '').replace(/^@+/, '').trim();
}

/** Публичный URL профиля/страницы из поля username (как в API): цифры → profile.php, иначе slug; поддержка старых полных URL в БД. */
function _facebookProfileUrlFromUsernameField(raw) {
  const s = _normUser(raw);
  if (!s) return null;
  if (/^https?:\/\//i.test(s)) {
    try {
      const url = new URL(s);
      const hostOk = /facebook\.com$/i.test(url.hostname) || url.hostname.endsWith('.facebook.com') || /^fb\.com$/i.test(url.hostname);
      if (!hostOk) return null;
      const id = url.searchParams.get('id');
      if (url.pathname.toLowerCase().includes('profile.php') && id && /^\d+$/.test(id)) return `https://www.facebook.com/profile.php?id=${encodeURIComponent(id)}`;
      const segs = url.pathname.split('/').filter(Boolean);
      const first = segs[0];
      if (first && /^\d+$/.test(first)) return `https://www.facebook.com/profile.php?id=${encodeURIComponent(first)}`;
      if (first && !/\.php$/i.test(first)) return `https://www.facebook.com/${encodeURIComponent(first)}`;
      return `${url.origin}${url.pathname}`;
    } catch (_) {
      return null;
    }
  }
  if (/profile\.php/i.test(s) && /\bid=\d+/i.test(s)) {
    const m = s.match(/\bid=(\d+)/i);
    if (m) return `https://www.facebook.com/profile.php?id=${encodeURIComponent(m[1])}`;
  }
  if (/^\d+$/.test(s)) return `https://www.facebook.com/profile.php?id=${encodeURIComponent(s)}`;
  return `https://www.facebook.com/${encodeURIComponent(s)}`;
}
function _externalProfileUrl(platform, username) {
  const u = _normUser(username);
  if (!u) return null;
  switch (String(platform || '')) {
    case 'tiktok':
      return `https://www.tiktok.com/@${encodeURIComponent(u)}`;
    case 'instagram':
      return `https://www.instagram.com/${encodeURIComponent(u)}/`;
    case 'youtube':
      if (/^UC[\w-]{10,}$/i.test(u)) return `https://www.youtube.com/channel/${encodeURIComponent(u)}`;
      return `https://www.youtube.com/@${encodeURIComponent(u)}`;
    case 'telegram':
      return `https://t.me/${encodeURIComponent(u)}`;
    case 'x':
      return `https://x.com/${encodeURIComponent(u)}`;
    case 'threads':
      return `https://www.threads.net/@${encodeURIComponent(u)}`;
    case 'facebook':
      return _facebookProfileUrlFromUsernameField(u);
    case 'rumble':
      return `https://rumble.com/c/${encodeURIComponent(u)}`;
    case 'reddit':
      return `https://www.reddit.com/r/${encodeURIComponent(u)}/`;
    default:
      return null;
  }
}

/** Ссылка на публикацию: сначала post_url из БД, иначе собираем из platform + username + external_id. */
function _postOpenUrl(platform, username, externalId, postUrl) {
  const direct = String(postUrl || '').trim();
  if (/^https?:\/\//i.test(direct)) return direct;
  const u = _normUser(username);
  const ext = String(externalId || '').trim();
  if (!ext) return null;
  switch (String(platform || '')) {
    case 'tiktok':
      return u ? `https://www.tiktok.com/@${encodeURIComponent(u)}/video/${encodeURIComponent(ext)}` : null;
    case 'instagram':
      if (/^[A-Za-z0-9_-]+$/.test(ext)) {
        return `https://www.instagram.com/p/${encodeURIComponent(ext)}/`;
      }
      return null;
    case 'youtube':
      return `https://www.youtube.com/watch?v=${encodeURIComponent(ext)}`;
    case 'telegram':
      return u ? `https://t.me/${encodeURIComponent(u)}/${encodeURIComponent(ext)}` : null;
    case 'x':
      return u ? `https://x.com/${encodeURIComponent(u)}/status/${encodeURIComponent(ext)}` : null;
    case 'threads':
      return `https://www.threads.com/t/${encodeURIComponent(ext)}`;
    case 'facebook':
      if (ext.startsWith('http')) return ext;
      return u ? `https://www.facebook.com/${encodeURIComponent(u)}/posts/${encodeURIComponent(ext)}` : null;
    case 'reddit':
      if (ext.startsWith('/')) return `https://www.reddit.com${ext}`;
      if (ext.startsWith('http')) return ext;
      return null;
    case 'rumble':
      if (ext.startsWith('http')) return ext;
      return u ? `https://rumble.com/c/${encodeURIComponent(u)}` : null;
    default:
      return null;
  }
}
function _openPostInNewTab(platform, username, externalId, postUrl) {
  const href = _postOpenUrl(platform, username, externalId, postUrl);
  if (!href) return false;
  window.open(href, '_blank', 'noopener,noreferrer');
  return true;
}
function _postScrapeNotFound(p) {
  return !!(p && (p.scrape_not_found || p.missing_from_scrape_at));
}

/** Оранжевая точка-индикатор (как зелёная на кнопке «Автообновление»). */
function ScrapeMissingDot({
  size = 8,
  marginRight,
  style
}) {
  const color = '#fb923c';
  return /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true,
    style: {
      width: size,
      height: size,
      borderRadius: 999,
      background: color,
      display: 'inline-block',
      flexShrink: 0,
      marginRight: marginRight ?? 0,
      boxShadow: `0 0 8px ${color}`,
      ...style
    }
  });
}
async function _deleteJson(url) {
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}${url}`, {
        method: 'DELETE'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${base}${url}`);
      return null;
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error(`Failed to delete ${url}`)));
}
function AccountAvatar({
  src,
  name,
  size = 36,
  borderColor = 'rgba(106,169,255,0.25)',
  fallbackBg = 'linear-gradient(135deg, #6aa9ff40, #ec489940)'
}) {
  const [broken, setBroken] = React.useState(false);
  const showImage = !!src && !broken;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      borderRadius: 999,
      overflow: 'hidden',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      border: `1px solid ${borderColor}`,
      background: fallbackBg,
      flexShrink: 0
    }
  }, showImage ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name || 'avatar',
    onError: () => setBroken(true),
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover',
      display: 'block'
    }
  }) : /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: Math.max(12, Math.round(size * 0.36)),
      fontWeight: 700,
      color: '#fff'
    }
  }, String(name || '?').charAt(0).toUpperCase()));
}
function EyeIcon({
  size = 12,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    "aria-hidden": "true",
    style: {
      display: 'block'
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z",
    fill: "none",
    stroke: color,
    strokeWidth: "1.8",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "3.2",
    fill: "none",
    stroke: color,
    strokeWidth: "1.8"
  }));
}
function InfoIcon({
  size = 12,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    "aria-hidden": "true",
    style: {
      display: 'block'
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9",
    fill: "none",
    stroke: color,
    strokeWidth: "1.8"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "8",
    r: "1.3",
    fill: color
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 11v6",
    stroke: color,
    strokeWidth: "1.8",
    strokeLinecap: "round"
  }));
}

/** Иконка «прирост» — переключение сортировки по дельтам в шапке таблицы аккаунтов */
function DeltaGrowthIcon({
  size = 17,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    "aria-hidden": "true",
    style: {
      display: 'block'
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M4 19h16M7 15l4-4 3 3 6-7",
    fill: "none",
    stroke: color,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 8h3.5V11.5",
    fill: "none",
    stroke: color,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }));
}
function ClockIcon({
  size = 18,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    "aria-hidden": true
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9",
    stroke: color,
    strokeWidth: "2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 7v5l3 2",
    stroke: color,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }));
}
function _sortScheduleTimes(times) {
  return [...new Set((Array.isArray(times) ? times : []).map(t => String(t).trim()).filter(t => /^\d{2}:\d{2}$/.test(t)))].sort((a, b) => {
    const [ah, am] = a.split(':').map(Number);
    const [bh, bm] = b.split(':').map(Number);
    return ah * 60 + am - (bh * 60 + bm);
  });
}
const DEFAULT_AUTO_REFRESH_TIMES = ['06:00', '12:00', '18:00', '00:00'];

/** Слоты из API как есть (пустой список = ни один слот не выбран). */
function _scheduleTimesFromServer(sched) {
  return _sortScheduleTimes(sched && sched.times);
}
function ScheduleTimesEditorModal({
  accent,
  customSlots,
  onClose,
  onApply
}) {
  const [draftTimes, setDraftTimes] = useStateMd(() => _sortScheduleTimes(customSlots));
  const [newTime, setNewTime] = useStateMd('');
  const addTime = () => {
    const t = String(newTime || '').trim();
    if (!/^\d{2}:\d{2}$/.test(t)) return;
    if (DEFAULT_AUTO_REFRESH_TIMES.includes(t)) return;
    setDraftTimes(prev => _sortScheduleTimes([...prev, t]));
    setNewTime('');
  };
  const removeTime = timeValue => {
    const t = String(timeValue || '').trim();
    setDraftTimes(prev => {
      const next = _sortScheduleTimes(prev.filter(x => x !== t));
      onApply(next);
      return next;
    });
  };
  const apply = () => {
    onApply(_sortScheduleTimes(draftTimes));
    onClose();
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 110,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.72)',
      padding: 16
    },
    onClick: e => {
      if (e.target === e.currentTarget) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": true,
    "aria-labelledby": "schedule-times-editor-title",
    onClick: e => e.stopPropagation(),
    style: {
      width: '100%',
      maxWidth: 400,
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(18,20,28,0.98)',
      padding: 20,
      boxShadow: '0 24px 56px rgba(0,0,0,0.65)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      display: 'grid',
      placeItems: 'center',
      color: 'var(--ink-dim)'
    }
  }, /*#__PURE__*/React.createElement(ClockIcon, {
    size: 18
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    id: "schedule-times-editor-title",
    style: {
      margin: 0,
      fontSize: 17,
      color: '#fff'
    }
  }, "\u0412\u0440\u0435\u043C\u044F \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '6px 0 0',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, "\u0417\u0434\u0435\u0441\u044C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043E\u043F\u043E\u043B\u043D\u0438\u0442\u0435\u043B\u044C\u043D\u044B\u0435 \u0441\u043B\u043E\u0442\u044B (\u043D\u0435 06:00 / 12:00 / 18:00 / 00:00). \xAB\u0423\u0434\u0430\u043B\u0438\u0442\u044C\xBB \u0441\u0440\u0430\u0437\u0443 \u0443\u0431\u0438\u0440\u0430\u0435\u0442 \u0432\u0440\u0435\u043C\u044F \u0438\u0437 \u0441\u043F\u0438\u0441\u043A\u0430."))), draftTimes.length === 0 ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 12px',
      fontSize: 13,
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0435\u0442 \u0441\u043B\u043E\u0442\u043E\u0432 \u2014 \u043F\u0440\u0438 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0438\u0438 \u043F\u043E\u0434\u0441\u0442\u0430\u0432\u044F\u0442\u0441\u044F \u0437\u043D\u0430\u0447\u0435\u043D\u0438\u044F \u043F\u043E \u0443\u043C\u043E\u043B\u0447\u0430\u043D\u0438\u044E.") : /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      marginBottom: 12,
      maxHeight: 220,
      overflowY: 'auto'
    }
  }, draftTimes.map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
      padding: '10px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.02)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: 'var(--ink)'
    }
  }, t), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => removeTime(t),
    title: `Удалить ${t}`,
    style: {
      padding: '6px 10px',
      borderRadius: 8,
      border: '1px solid rgba(239,68,68,0.45)',
      background: 'rgba(239,68,68,0.12)',
      color: '#fca5a5',
      cursor: 'pointer',
      fontSize: 12
    }
  }, "\u0423\u0434\u0430\u043B\u0438\u0442\u044C")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "time",
    value: newTime,
    onChange: e => setNewTime(e.target.value),
    style: {
      flex: 1,
      padding: '11px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink)',
      fontSize: 13,
      fontFamily: 'JetBrains Mono, monospace'
    }
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: addTime,
    style: {
      padding: '11px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13
    }
  }, "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    style: {
      flex: 1,
      padding: 12,
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: apply,
    style: {
      flex: 1,
      padding: 12,
      borderRadius: 10,
      border: 'none',
      background: accent,
      color: '#000',
      fontWeight: 600,
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u041F\u0440\u0438\u043C\u0435\u043D\u0438\u0442\u044C"))));
}
function InfoButton({
  onClick,
  title,
  size = 12
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    title: title,
    style: {
      width: 18,
      height: 18,
      border: 'none',
      background: 'transparent',
      color: '#94a3b8',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      padding: 0,
      lineHeight: 0,
      outline: 'none',
      boxShadow: 'none',
      appearance: 'none',
      WebkitAppearance: 'none'
    }
  }, /*#__PURE__*/React.createElement(InfoIcon, {
    size: size,
    color: "#94a3b8"
  }));
}
function AvailabilityBadge({
  unavailable,
  reason
}) {
  if (!unavailable) return null;
  return /*#__PURE__*/React.createElement("span", {
    title: reason ? String(reason) : 'Профиль недоступен',
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 10px',
      borderRadius: 999,
      background: 'rgba(239,68,68,0.14)',
      border: '1px solid rgba(239,68,68,0.34)',
      color: '#fca5a5',
      fontSize: 11,
      fontWeight: 600,
      boxShadow: '0 0 10px rgba(239,68,68,0.2)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: 999,
      background: '#ef4444'
    }
  }), "\u041D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D");
}
function useIsMobile(breakpoint = 900) {
  const [isMobile, setIsMobile] = React.useState(() => window.innerWidth <= breakpoint);
  React.useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= breakpoint);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpoint]);
  return isMobile;
}
function MobileGlobalStyle() {
  return /*#__PURE__*/React.createElement("style", null, `
      @media (max-width: 980px) {
        html, body { font-size: 14px; }
        input, button, select, textarea { font-size: 16px !important; }
      }
    `);
}
async function loadDashboardData() {
  LOAD_STATE = {
    hasError: false,
    errorMessage: ''
  };
  let hadAnySuccess = false;
  DELTA_PERIOD_CACHE = {
    1: null,
    7: null,
    30: null
  };
  const [scheduleR, autoStatusR] = await Promise.all([_fetchJsonSoft('/api/accounts/schedule/'), _fetchJsonSoft('/api/accounts/auto-refresh-status/')]);
  // Раньше hadAnySuccess не учитывал этот батч: при живом API, но сбое summary/accounts,
  // показывалось «не удалось связаться», хотя /api уже отвечал (вводило в заблуждение).
  if (scheduleR.ok || autoStatusR.ok) {
    hadAnySuccess = true;
  }
  const scheduleResp = scheduleR.ok ? scheduleR.data : null;
  const autoStatusResp = autoStatusR.ok ? autoStatusR.data : null;
  TV_AUTO_SCHEDULE_LABEL = _buildTvAutoScheduleLabel(scheduleResp);
  TV_AUTO_IS_RUNNING = !!(autoStatusResp && autoStatusResp.is_running);
  {
    const raw = scheduleResp && scheduleResp.account_delta_period_days != null ? Number(scheduleResp.account_delta_period_days) : 1;
    ACCOUNT_DELTA_PERIOD_DAYS = [1, 7, 30].includes(raw) ? raw : 1;
  }
  const p = ACCOUNT_DELTA_PERIOD_DAYS;
  const [summaryR, accountsR, profilesR, topR, authR, allPlatformsR, autoSeriesR] = await Promise.all([_fetchJsonSoft(`/api/accounts/summary/?include_hidden=1&delta_period_days=${p}`), _fetchJsonSoft(`/api/accounts/?include_hidden=1&delta_period_days=${p}`), _fetchJsonSoft('/api/accounts/profiles/?include_hidden_profiles=1'), _fetchJsonSoft('/api/accounts/analytics/top-posts/?period=1d&sort_by=view_delta&page_size=8&min_views=0'), _fetchJsonSoft('/api/settings/status/'), _fetchJsonSoft('/api/accounts/platforms/'), _fetchJsonSoft('/api/accounts/auto-refresh-series/')]);
  const summary = summaryR.ok ? summaryR.data : null;
  if (summary) {
    hadAnySuccess = true;
    TOTAL = _totalFromSummary(summary);
    PLATFORMS = _platformsFromSummary(summary);
    TREND_24H = _buildAscendingTrend(TOTAL.views.value, TOTAL.views.delta, 24);
    TREND_7D = _buildAscendingTrend(TOTAL.views.value, TOTAL.views.delta * 3, 7);
  }
  const autoSeriesResp = autoSeriesR.ok ? autoSeriesR.data : null;
  if (autoSeriesResp && Array.isArray(autoSeriesResp.points)) {
    hadAnySuccess = true;
    AUTO_REFRESH_SERIES = autoSeriesResp.points.map(p => ({
      measured_at: String(p.measured_at || ''),
      slot_label: String(p.slot_label || ''),
      source: String(p.source || ''),
      view_count_total: Number(p.view_count_total || 0),
      view_delta_from_prev_point: Number(p.view_delta_from_prev_point || 0),
      view_delta_from_day_start: Number(p.view_delta_from_day_start || 0),
      platform_deltas: p && typeof p.platform_deltas === 'object' ? p.platform_deltas : {}
    }));
    const realTrend = _buildTrendFromSeries(AUTO_REFRESH_SERIES, 24);
    if (realTrend && realTrend.length > 1) {
      TREND_24H = realTrend;
    }
  } else {
    AUTO_REFRESH_SERIES = [];
  }
  const allPlatformsResp = allPlatformsR.ok ? allPlatformsR.data : null;
  if (Array.isArray(allPlatformsResp)) {
    hadAnySuccess = true;
    ALL_PLATFORMS = allPlatformsResp.map(p => ({
      id: String(p.value || ''),
      label: String(p.label || p.value || ''),
      color: PLATFORM_COLORS[String(p.value || '')] || '#9ca3af',
      hidden: !!p.hidden
    }));
  }
  const profilesResp = profilesR.ok ? profilesR.data : null;
  if (Array.isArray(profilesResp)) {
    hadAnySuccess = true;
    PROFILES = [{
      id: 'none',
      label: 'Без профиля',
      color: '#525a70',
      accounts: 0
    }, ...profilesResp.map((p, idx) => ({
      id: String(p.id),
      label: String(p.name || `Профиль ${idx + 1}`),
      color: String(p.color || PROFILE_PALETTE[idx % PROFILE_PALETTE.length]),
      accounts: Number(p.account_count || 0)
    }))];
  }
  const accountsResp = accountsR.ok ? accountsR.data : null;
  if (Array.isArray(accountsResp)) {
    hadAnySuccess = true;
    ACCOUNTS = accountsResp.map(_mapAccountApiRow);
    const byProfileFromAccounts = new Map();
    for (const acc of ACCOUNTS) {
      const key = String(acc.profile || 'none');
      byProfileFromAccounts.set(key, (byProfileFromAccounts.get(key) || 0) + 1);
    }
    PROFILES = PROFILES.map(p => ({
      ...p,
      accounts: Number(byProfileFromAccounts.get(String(p.id)) || 0)
    }));
    if (summary && Array.isArray(accountsResp)) {
      const snap = _buildDeltaSnapshot(summary, accountsResp);
      if (snap) _storeDeltaCacheForPeriod(p, snap);
    }
    _scheduleDeltaPrefetchExcept(p);
  }
  const topResp = topR.ok ? topR.data : null;
  if (topResp && Array.isArray(topResp.items)) {
    hadAnySuccess = true;
    POSTS = topResp.items.map(p => ({
      handle: p?.account?.platform === 'rumble' ? String(p?.account?.username || '') : `@${String(p?.account?.username || '')}`,
      platform: String(p?.account?.platform || ''),
      date: _ruShortDate(p?.posted_at || '').slice(0, 8).replace(/\./g, '.'),
      text: String(p?.description || ''),
      delta: Number(p?.view_delta || 0),
      views: Number(p?.view_count || 0),
      likes: Number(p?.like_count || 0),
      er: Number(p?.engagement_rate || 0)
    }));
  }
  const authResp = authR.ok ? authR.data : null;
  if (authResp) {
    hadAnySuccess = true;
    const states = [['tiktok', 'TikTok'], ['instagram', 'Instagram'], ['telegram', 'Telegram'], ['youtube', 'YouTube'], ['x', 'X (Twitter)'], ['threads', 'Threads'], ['facebook', 'Facebook'], ['rumble', 'Rumble'], ['reddit', 'Reddit']];
    const _authSessionsFromBlock = block => states.map(([id, name]) => {
      const s = block && block[id] || {};
      const hasSession = !!s.has_session;
      const expires = id === 'tiktok' ? s.min_expires || null : null;
      const days = _daysUntil(expires);
      const nearExpiry = hasSession && days != null && days <= 10;
      return {
        id,
        name,
        state: hasSession ? 'active' : 'expired',
        updated: s.last_updated ? _ruShortDate(String(s.last_updated)) : null,
        warn: nearExpiry,
        account: s.username ? `@${s.username}` : null,
        expires: expires ? _expiryBadge(days) : null,
        meta: id === 'tiktok' && s.min_expires_name ? String(s.min_expires_name) : null,
        hasSession
      };
    });
    AUTH_SESSIONS = _authSessionsFromBlock(authResp);
  }
  if (!hadAnySuccess) {
    const parts = ['Не удалось получить данные с backend API (все запросы завершились ошибкой).', '1) Запустите Django из папки backend: python manage.py runserver (порт 8000).', '2) trycloudflare: из папки new_frontend выполните npm run tunnel — конфиг cloudflared.5174.yml (маршруты ^/api → :8000, остальное → :5174). Команда только на 5174 API не отдаёт.', '3) Если API на другом origin: localStorage.setItem("new_frontend_api_base", "https://…").'];
    const hintTry = /trycloudflare\.com/i.test(window.location.hostname || '');
    if (hintTry) {
      parts.push('Сейчас страница на trycloudflare: откройте DevTools → Network и проверьте запрос к /api/… (не должно быть 404/HTML от статики на 5174).');
    }
    const errBits = [scheduleR, autoStatusR, summaryR, accountsR, profilesR, topR, authR, allPlatformsR, autoSeriesR].filter(r => r && !r.ok && r.error).slice(0, 4).map(r => r.error instanceof Error ? r.error.message : String(r.error));
    if (errBits.length) {
      parts.push('Детали: ' + errBits.join(' | '));
    }
    LOAD_STATE = {
      hasError: true,
      errorMessage: parts.join('\n')
    };
  }
  recomputeMeta();
}
recomputeMeta();
function _extractUsernameFromText(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  if (text.startsWith('@')) return text.slice(1);
  const m = text.match(/(?:@|\/c\/|\/r\/)?([a-zA-Z0-9._-]{2,})\/?$/);
  return m ? m[1] : text.replace(/^@/, '');
}
function _parseBulkLine(line) {
  const s = String(line || '').trim();
  if (!s) return null;
  const l = s.toLowerCase();
  if (l.includes('tiktok.com')) return {
    platform: 'tiktok',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('instagram.com')) return {
    platform: 'instagram',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('youtube.com') || l.includes('youtu.be')) return {
    platform: 'youtube',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('threads.net') || l.includes('threads.com')) return {
    platform: 'threads',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('twitter.com') || l.includes('x.com')) return {
    platform: 'x',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('facebook.com') || l.includes('fb.com')) {
    const qid = s.match(/[?&]id=(\d{6,})/i);
    if (qid) return {
      platform: 'facebook',
      username: qid[1]
    };
    try {
      const href = s.startsWith('http') ? s : 'https://' + s.replace(/^\/+/, '');
      const url = new URL(href);
      const hostOk = /facebook\.com$/i.test(url.hostname) || url.hostname.endsWith('.facebook.com') || /^fb\.com$/i.test(url.hostname);
      if (!hostOk) return {
        platform: 'facebook',
        username: _extractUsernameFromText(s)
      };
      const parts = url.pathname.split('/').filter(Boolean);
      const seg = parts[0];
      if (!seg) return {
        platform: 'facebook',
        username: _extractUsernameFromText(s)
      };
      if (seg.toLowerCase() === 'profile.php') {
        const id = url.searchParams.get('id');
        if (id && /^\d+$/.test(id)) return {
          platform: 'facebook',
          username: id
        };
      }
      if (/^\d+$/.test(seg)) return {
        platform: 'facebook',
        username: seg
      };
      return {
        platform: 'facebook',
        username: decodeURIComponent(seg)
      };
    } catch (_) {
      return {
        platform: 'facebook',
        username: _extractUsernameFromText(s)
      };
    }
  }
  if (l.includes('t.me')) return {
    platform: 'telegram',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('reddit.com')) return {
    platform: 'reddit',
    username: _extractUsernameFromText(s)
  };
  if (l.includes('rumble.com')) return {
    platform: 'rumble',
    username: _extractUsernameFromText(s)
  };
  return null;
}
function _bulkImportEntryLabel(parsed, line) {
  const u = String(parsed?.username || '').replace(/^@/, '');
  const p = String(parsed?.platform || '');
  return u ? `${p}/@${u}` : String(line || '').trim();
}
function _friendlyBulkImportError(message) {
  const m = String(message || '').toLowerCase();
  if (
    m.includes('unique') ||
    m.includes('уже есть') ||
    m.includes('уникальн') ||
    m.includes('already exists') ||
    m.includes('must make a unique set')
  ) {
    return 'Уже есть в базе';
  }
  return String(message || 'Ошибка').replace(/\s*\(HTTP \d+\)\s*$/i, '').trim() || 'Ошибка';
}
async function _importAccountFromBulkLine(parsed, profileId) {
  const payload = {
    platform: parsed.platform,
    username: String(parsed.username || '').replace(/^@/, ''),
    profile_id: profileId === 'none' ? null : Number(profileId)
  };
  const candidates = _apiBaseCandidates();
  let lastErr = null;
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/api/accounts/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      let body = null;
      try {
        body = await res.json();
      } catch (_) {}
      if (res.ok) {
        const action = body?.import_action || (res.status === 201 ? 'created' : 'unchanged');
        return {
          action
        };
      }
      throw new Error(await _errorMessageFromResponse(res, `HTTP ${res.status} for ${base}/api/accounts/`));
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(_apiTunnelDeadHint(lastErr || new Error('Failed to import account')));
}

// ===== atomic.jsx =====
// Atomic-themed visual primitives: orbits, particles, sparklines, dials, tickers.
// Uses pure SVG/CSS for crisp scaling on TVs.

const {
  useEffect,
  useRef,
  useState,
  useMemo
} = React;

// ────────────────────────────────────────────────────────────
// Orbit system: a nucleus surrounded by rotating particles. Used as the
// hero metaphor — each orbit ring represents a metric (followers/views/likes/posts).
// ────────────────────────────────────────────────────────────
function OrbitSystem({
  size = 720,
  rings,
  label,
  value,
  sub,
  color = '#6aa9ff'
}) {
  const cx = size / 2,
    cy = size / 2;
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${size} ${size}`,
    style: {
      width: '100%',
      height: '100%',
      display: 'block'
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("radialGradient", {
    id: "nuc-glow",
    cx: "50%",
    cy: "50%",
    r: "50%"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0%",
    stopColor: color,
    stopOpacity: "0.65"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "60%",
    stopColor: color,
    stopOpacity: "0.08"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "100%",
    stopColor: color,
    stopOpacity: "0"
  })), /*#__PURE__*/React.createElement("filter", {
    id: "nuc-blur"
  }, /*#__PURE__*/React.createElement("feGaussianBlur", {
    stdDeviation: "3"
  }))), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cy,
    r: size * 0.18,
    fill: "url(#nuc-glow)"
  }), rings.map((r, i) => {
    const rx = r.rx * (size / 720);
    const ry = r.ry * (size / 720);
    const dur = r.dur || 28 + i * 6;
    const rot = r.rot || 0;
    return /*#__PURE__*/React.createElement("g", {
      key: i,
      transform: `rotate(${rot} ${cx} ${cy})`
    }, /*#__PURE__*/React.createElement("ellipse", {
      cx: cx,
      cy: cy,
      rx: rx,
      ry: ry,
      fill: "none",
      stroke: r.color || color,
      strokeOpacity: r.opacity ?? 0.28,
      strokeWidth: "1",
      strokeDasharray: r.dash || ''
    }), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("animateTransform", {
      attributeName: "transform",
      type: "rotate",
      from: `0 ${cx} ${cy}`,
      to: `360 ${cx} ${cy}`,
      dur: `${dur}s`,
      repeatCount: "indefinite"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: cx + rx,
      cy: cy,
      r: r.particleR || 5,
      fill: r.color || color
    }, /*#__PURE__*/React.createElement("animate", {
      attributeName: "r",
      values: `${(r.particleR || 5) * 0.7};${(r.particleR || 5) * 1.1};${(r.particleR || 5) * 0.7}`,
      dur: "2.4s",
      repeatCount: "indefinite"
    })), /*#__PURE__*/React.createElement("circle", {
      cx: cx + rx,
      cy: cy,
      r: (r.particleR || 5) * 2.4,
      fill: r.color || color,
      opacity: "0.18",
      filter: "url(#nuc-blur)"
    })));
  }), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cy,
    r: size * 0.04,
    fill: color
  }), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cy,
    r: size * 0.025,
    fill: "#fff",
    opacity: "0.9"
  }), label && /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cy - size * 0.13,
    textAnchor: "middle",
    fill: "rgba(255,255,255,0.5)",
    fontFamily: "JetBrains Mono, monospace",
    fontSize: size * 0.022,
    letterSpacing: "0.2em"
  }, label)), value && /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cy + size * 0.32,
    textAnchor: "middle",
    fill: "#fff",
    fontFamily: "Space Grotesk, sans-serif",
    fontWeight: "700",
    fontSize: size * 0.075
  }, value), sub && /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cy + size * 0.38,
    textAnchor: "middle",
    fill: color,
    fontFamily: "JetBrains Mono, monospace",
    fontSize: size * 0.028
  }, sub));
}

// ────────────────────────────────────────────────────────────
// Sparkline — minimalist, atomic, with optional area fill.
// ────────────────────────────────────────────────────────────
function Sparkline({
  data,
  color = '#6aa9ff',
  width = 240,
  height = 60,
  fill = true,
  dot = true,
  strokeWidth = 1.6,
  stretch = false
}) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(1, max - min);
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => [i * stepX, height - (v - min) / range * (height - 6) - 3]);
  const path = points.map((p, i) => i === 0 ? `M${p[0].toFixed(1)},${p[1].toFixed(1)}` : `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1];
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    style: {
      display: 'block',
      width: stretch ? '100%' : width,
      height
    },
    width: stretch ? undefined : width,
    height: height,
    preserveAspectRatio: "none"
  }, fill && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: `sparkfill-${color.replace('#', '')}`,
    x1: "0",
    x2: "0",
    y1: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0%",
    stopColor: color,
    stopOpacity: "0.35"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "100%",
    stopColor: color,
    stopOpacity: "0"
  }))), /*#__PURE__*/React.createElement("path", {
    d: areaPath,
    fill: `url(#sparkfill-${color.replace('#', '')})`
  })), /*#__PURE__*/React.createElement("path", {
    d: path,
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }), dot && /*#__PURE__*/React.createElement("circle", {
    cx: last[0],
    cy: last[1],
    r: 3,
    fill: color,
    stroke: "#0a0c12",
    strokeWidth: "2"
  }));
}

// ────────────────────────────────────────────────────────────
// Radial dial — used for percentages or composition.
// ────────────────────────────────────────────────────────────
function RadialDial({
  value = 0.5,
  size = 120,
  color = '#6aa9ff',
  track = 'rgba(255,255,255,0.06)',
  strokeWidth = 8,
  label,
  sub
}) {
  const r = (size - strokeWidth) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - value);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: size,
      height: size
    }
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${size} ${size}`,
    width: size,
    height: size,
    style: {
      transform: 'rotate(-90deg)'
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: track,
    strokeWidth: strokeWidth
  }), /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeDasharray: c,
    strokeDashoffset: offset,
    style: {
      transition: 'stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      textAlign: 'center'
    }
  }, label && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Space Grotesk',
      fontWeight: 700,
      fontSize: size * 0.22,
      color: '#fff',
      lineHeight: 1
    }
  }, label), sub && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: size * 0.09,
      color: 'rgba(255,255,255,0.5)',
      marginTop: 4,
      letterSpacing: '0.06em',
      textTransform: 'uppercase'
    }
  }, sub)));
}

// ────────────────────────────────────────────────────────────
// Particle field background — ambient atomic dust.
// ────────────────────────────────────────────────────────────
function ParticleField({
  count = 60,
  color = '#6aa9ff',
  opacity = 0.5
}) {
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
    const particles = Array.from({
      length: count
    }, () => ({
      x: Math.random(),
      y: Math.random(),
      vx: (Math.random() - 0.5) * 0.0006,
      vy: (Math.random() - 0.5) * 0.0006,
      r: Math.random() * 1.2 + 0.3,
      a: Math.random() * 0.5 + 0.15
    }));
    const tick = () => {
      const w = canvas.width / devicePixelRatio,
        h = canvas.height / devicePixelRatio;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = color;
      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
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
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, [count, color, opacity]);
  return /*#__PURE__*/React.createElement("canvas", {
    ref: canvasRef,
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%',
      pointerEvents: 'none'
    }
  });
}

// ────────────────────────────────────────────────────────────
// AtomicGrid — subtle technical grid background.
// ────────────────────────────────────────────────────────────
function AtomicGrid({
  opacity = 0.05,
  size = 48
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      pointerEvents: 'none',
      backgroundImage: `linear-gradient(rgba(255,255,255,${opacity}) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,${opacity}) 1px, transparent 1px)`,
      backgroundSize: `${size}px ${size}px`,
      maskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)',
      WebkitMaskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)'
    }
  });
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
    const tick = t => {
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
function PlatformGlyph({
  id,
  size = 18
}) {
  const isMobile = useIsMobile(980);
  const meta = PLATFORM_META[id];
  if (!meta) return null;
  const letter = meta.label.charAt(0);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: size * 0.7,
      letterSpacing: '0.05em'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      borderRadius: 4,
      background: 'rgba(255,255,255,0.04)',
      border: `1px solid ${meta.color}55`,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: meta.color,
      fontWeight: 700
    }
  }, letter), !isMobile && meta.label);
}
function ProfileBadge({
  id,
  dense = false
}) {
  const isMobile = useIsMobile(980);
  const p = PROFILE_META[id];
  if (!p) return null;
  const shortLabel = isMobile ? String(p.label || '').split(/\s+/).filter(Boolean).map(w => w[0]).join('').slice(0, 3).toUpperCase() || String(p.label || '').slice(0, 3) : p.label;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: dense ? '2px 8px' : '4px 10px',
      borderRadius: 999,
      background: `${p.color}1a`,
      color: p.color,
      fontSize: 12,
      fontWeight: 500,
      border: `1px solid ${p.color}33`
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: 999,
      background: p.color
    }
  }), shortLabel);
}

// ────────────────────────────────────────────────────────────
// Stat tile with delta
// ────────────────────────────────────────────────────────────
function StatTile({
  label,
  value,
  delta,
  color = '#6aa9ff',
  size = 'lg',
  spark
}) {
  const sizes = {
    sm: {
      label: 11,
      value: 28,
      delta: 13,
      pad: 16,
      lh: 1
    },
    md: {
      label: 12,
      value: 44,
      delta: 15,
      pad: 20,
      lh: 1
    },
    lg: {
      label: 13,
      value: 72,
      delta: 18,
      pad: 28,
      lh: 1
    },
    xl: {
      label: 14,
      value: 124,
      delta: 22,
      pad: 36,
      lh: 0.95
    },
    xxl: {
      label: 16,
      value: 168,
      delta: 26,
      pad: 44,
      lh: 0.92
    }
  };
  const s = sizes[size];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      padding: s.pad,
      borderRadius: 16,
      background: 'linear-gradient(180deg, rgba(255,255,255,0.025), rgba(255,255,255,0.01))',
      border: '1px solid var(--line)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 1,
      background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
      opacity: 0.5
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: s.label,
      color: 'var(--ink-mute)',
      textTransform: 'uppercase',
      letterSpacing: '0.18em'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: s.value,
      fontWeight: 700,
      color: '#fff',
      lineHeight: s.lh,
      marginTop: 8,
      letterSpacing: '-0.02em'
    }
  }, value), delta != null && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      marginTop: 8,
      fontSize: s.delta,
      color: delta >= 0 ? 'var(--accent-2)' : 'var(--danger)',
      fontWeight: 500
    }
  }, delta >= 0 ? '▲' : '▼', " ", delta >= 0 ? '+' : '', fmt(delta), " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-mute)',
      fontWeight: 400
    }
  }, "/24h")), spark && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      opacity: 0.9
    }
  }, spark));
}

// ────────────────────────────────────────────────────────────
// Section header (used across screens)
// ────────────────────────────────────────────────────────────
function SectionHeader({
  kicker,
  title,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("div", null, kicker && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      textTransform: 'uppercase',
      letterSpacing: '0.22em',
      marginBottom: 6
    }
  }, kicker), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 600,
      letterSpacing: '-0.01em'
    }
  }, title)), right);
}
Object.assign(window, {
  OrbitSystem,
  Sparkline,
  RadialDial,
  ParticleField,
  AtomicGrid,
  useCountUp,
  PlatformGlyph,
  ProfileBadge,
  StatTile,
  SectionHeader
});

// ===== screen-tv.jsx =====
// TV broadcast screen — auto-cycling fullscreen views.
// Three "scenes": Hero Atom, Platform Constellation, Top Accounts Leaderboard.
// All-data, no-input, transitions between scenes every 12s.

const {
  useEffect: useEffectTV,
  useState: useStateTV,
  useRef: useRefTV,
  useMemo: useMemoTV
} = React;
function TVScreen({
  tweaks,
  onExit
}) {
  const isMobile = useIsMobile(980);
  const mood = tweaks.tv_mood || 'mission'; // mission | bloomberg | calm
  const accent = tweaks.accent || '#6aa9ff';
  const accentSecondary = '#4ade80';
  const [scene, setScene] = useStateTV(0);
  const [now, setNow] = useStateTV(new Date());
  const [pulse, setPulse] = useStateTV(0);
  const [autoRunning, setAutoRunning] = useStateTV(!!TV_AUTO_IS_RUNNING);
  const [sceneAutoPaused, setSceneAutoPaused] = useStateTV(false);
  const wheelAccumRef = useRefTV(0);
  const wheelLockRef = useRefTV(false);
  const SCENES = ['atom', 'pulse', 'top'];
  const wheelStep = direction => {
    setScene(prev => {
      const base = Math.max(0, Math.min(SCENES.length - 1, Number(prev || 0)));
      return direction > 0 ? (base + 1) % SCENES.length : (base - 1 + SCENES.length) % SCENES.length;
    });
  };
  const onDesktopWheel = e => {
    if (isMobile) return;
    const dy = Number(e?.deltaY || 0);
    if (!Number.isFinite(dy) || Math.abs(dy) < 2) return;
    wheelAccumRef.current += dy;
    const threshold = 80;
    if (Math.abs(wheelAccumRef.current) < threshold) return;
    if (wheelLockRef.current) return;
    wheelLockRef.current = true;
    const direction = wheelAccumRef.current > 0 ? 1 : -1;
    wheelAccumRef.current = 0;
    wheelStep(direction);
    window.setTimeout(() => {
      wheelLockRef.current = false;
    }, 260);
  };
  useEffectTV(() => {
    if (sceneAutoPaused) return undefined;
    const id = setInterval(() => setScene(s => (s + 1) % SCENES.length), 14000);
    return () => clearInterval(id);
  }, [sceneAutoPaused]);
  useEffectTV(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffectTV(() => {
    const id = setInterval(() => setPulse(p => p + 1), 2200);
    return () => clearInterval(id);
  }, []);
  useEffectTV(() => {
    let cancelled = false;
    const refreshAutoStatus = async () => {
      try {
        const st = await _fetchJson('/api/accounts/auto-refresh-status/');
        if (!cancelled) setAutoRunning(!!st?.is_running);
      } catch {
        // keep last known state
      }
    };
    void refreshAutoStatus();
    const id = setInterval(() => {
      void refreshAutoStatus();
    }, 9000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  const moodTone = mood === 'bloomberg' ? {
    bg: '#000',
    accent: '#ffb000',
    surface: 'rgba(255,255,255,0.02)'
  } : mood === 'calm' ? {
    bg: '#070a10',
    accent: '#a8c9ff',
    surface: 'rgba(255,255,255,0.02)'
  } : {
    bg: '#050608',
    accent: accent,
    surface: 'rgba(255,255,255,0.025)'
  };
  if (isMobile) {
    const touchStartXRef = useRefTV(null);
    const touchStartYRef = useRefTV(null);
    const items = [{
      label: 'ПОДПИСЧИКИ',
      value: TOTAL.followers.value,
      delta: TOTAL.followers.delta,
      color: '#22c55e',
      spark: _buildYesterdayBaselineSpark(TOTAL.followers.delta, TOTAL.followers.yesterdayDelta, 24, 10)
    }, {
      label: 'ПРОСМОТРЫ',
      value: TOTAL.views.value,
      delta: TOTAL.views.delta,
      color: '#ec4899',
      spark: _buildYesterdayBaselineSpark(TOTAL.views.delta, TOTAL.views.yesterdayDelta, 24, 10)
    }, {
      label: 'ЛАЙКИ',
      value: TOTAL.likes.value,
      delta: TOTAL.likes.delta,
      color: '#f59e0b',
      spark: _buildYesterdayBaselineSpark(TOTAL.likes.delta, TOTAL.likes.yesterdayDelta, 24, 10)
    }, {
      label: 'ПУБЛИКАЦИИ',
      value: TOTAL.posts.value,
      delta: TOTAL.posts.delta,
      color: tweaks.accent || '#6aa9ff',
      spark: _buildYesterdayBaselineSpark(TOTAL.posts.delta, TOTAL.posts.yesterdayDelta, 24, 10)
    }];
    const mobileSeriesAll = Array.isArray(AUTO_REFRESH_SERIES) ? AUTO_REFRESH_SERIES : [];
    const mobileNowTs = Date.now();
    const mobileWindowMs = 24 * 60 * 60 * 1000;
    const mobileSlackMs = 120000;
    const mobileSeries = _aggregateSeriesByHour(mobileSeriesAll.filter(p => {
      const ts = Date.parse(String(p?.measured_at || ''));
      return Number.isFinite(ts) && ts <= mobileNowTs;
    }), mobileNowTs, 24);
    const mobileLast = mobileSeries.length > 0 ? mobileSeries[mobileSeries.length - 1] : null;
    const mobileLive = Number(TOTAL.views.value || 0);
    const mobileSnap = Number(mobileLast?.view_count_total || 0);
    const mobileBaseDay = Number(mobileLast?.view_delta_from_day_start || 0);
    const mobileDayDeltaViews = mobileLast ? mobileBaseDay + (mobileLive - mobileSnap) : Number(TOTAL.views.delta || 0);
    const mobileTopMovers = [...ACCOUNTS].sort((a, b) => Number(b.dViews || 0) - Number(a.dViews || 0)).slice(0, 6);
    const mobileTopMax = mobileTopMovers.length > 0 ? Math.max(1, ...mobileTopMovers.map(a => Number(a.dViews || 0))) : 1;
    const mobilePlatformPulse = (PLATFORMS || []).map(p => {
      const pulseData = _platformPulseFromSeries(mobileSeries, p.id);
      const hasPulseVariation = pulseData.hasVariation && Array.isArray(pulseData.data) && pulseData.data.length > 1;
      const fallbackValue = Math.round(Number(TOTAL.views.delta || 0) * Number(p.share || 0));
      return {
        id: p.id,
        label: p.label,
        color: p.color,
        value: hasPulseVariation ? Math.round(Number(pulseData.totalDelta || 0)) : fallbackValue,
        hasPulseVariation,
        data: hasPulseVariation ? _normalizeSparkData(pulseData.data) : _normalizeSparkData(TREND_24H.map((v, idx) => v * (p.share + 0.4) + Math.sin(idx) * 30))
      };
    }).sort((a, b) => Math.abs(Number(b.value || 0)) - Math.abs(Number(a.value || 0))).slice(0, 5);
    const onMobileTouchStart = e => {
      touchStartXRef.current = Number(e?.touches?.[0]?.clientX || 0);
      touchStartYRef.current = Number(e?.touches?.[0]?.clientY || 0);
    };
    const onMobileTouchEnd = e => {
      const startX = touchStartXRef.current;
      const startY = touchStartYRef.current;
      if (startX == null) return;
      const endX = Number(e?.changedTouches?.[0]?.clientX || 0);
      const endY = Number(e?.changedTouches?.[0]?.clientY || 0);
      const dx = endX - startX;
      const dy = endY - Number(startY || 0);
      const absDx = Math.abs(dx);
      const absDy = Math.abs(dy);
      touchStartXRef.current = null;
      touchStartYRef.current = null;
      if (absDx < 24) return;
      if (absDx <= absDy + 6) return;
      const base = Math.max(0, Math.min(SCENES.length - 1, Number(scene || 0)));
      const next = dx < 0 ? (base - 1 + SCENES.length) % SCENES.length : (base + 1) % SCENES.length;
      setScene(next);
    };
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'fixed',
        inset: 0,
        background: moodTone.bg,
        color: '#fff',
        overflowY: 'auto',
        fontFamily: 'Space Grotesk, sans-serif'
      },
      "data-screen-label": "TV Broadcast"
    }, /*#__PURE__*/React.createElement(AtomicGrid, {
      opacity: 0.028,
      size: 56
    }), /*#__PURE__*/React.createElement(TVHeader, {
      now: now,
      accent: moodTone.accent,
      mood: mood,
      onExit: onExit,
      autoScheduleLabel: TV_AUTO_SCHEDULE_LABEL,
      autoIsRunning: autoRunning
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        padding: '88px 0 104px',
        zIndex: 2
      }
    }, /*#__PURE__*/React.createElement("div", {
      onTouchStart: onMobileTouchStart,
      onTouchEnd: onMobileTouchEnd,
      style: {
        padding: '0 10px'
      }
    }, scene === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr',
        gap: 10
      }
    }, items.map(item => /*#__PURE__*/React.createElement("div", {
      key: item.label,
      style: {
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.008))',
        padding: '12px 12px 10px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 10,
        color: 'rgba(255,255,255,0.6)',
        letterSpacing: '0.18em'
      }
    }, item.label), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 10,
        color: 'rgba(255,255,255,0.35)',
        letterSpacing: '0.14em'
      }
    }, "24H")), /*#__PURE__*/React.createElement("div", {
      className: "tnum",
      style: {
        fontSize: 58,
        fontWeight: 700,
        letterSpacing: '-0.03em',
        lineHeight: 0.9,
        marginTop: 6
      }
    }, fmt(item.value)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'flex-end',
        gap: 10,
        marginTop: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono tnum",
      style: {
        fontSize: 28,
        color: item.color,
        fontWeight: 600,
        minWidth: 84
      }
    }, item.delta >= 0 ? '+' : '', fmt(item.delta)), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        height: 72
      }
    }, /*#__PURE__*/React.createElement(ResponsiveSpark, {
      data: item.spark,
      color: item.color,
      scaleMin: 0,
      scaleMax: 10
    })))))), scene === 1 && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      style: {
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(255,255,255,0.02)',
        padding: '10px 10px 12px',
        marginBottom: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 10,
        color: 'rgba(255,255,255,0.55)',
        letterSpacing: '0.18em'
      }
    }, "VIEWS \xB7 LAST 24H"), /*#__PURE__*/React.createElement("div", {
      className: "tnum",
      style: {
        fontSize: 46,
        fontWeight: 700,
        marginTop: 6,
        lineHeight: 0.95
      }
    }, fmtSign(mobileDayDeltaViews)), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 10,
        height: 190
      }
    }, /*#__PURE__*/React.createElement(BigChart, {
      accent: moodTone.accent,
      series: mobileSeries,
      isMobile: true
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 8
      }
    }, mobilePlatformPulse.map(p => /*#__PURE__*/React.createElement("div", {
      key: p.id,
      style: {
        borderRadius: 12,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(255,255,255,0.015)',
        padding: '9px 10px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 999,
        background: p.color
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14,
        fontWeight: 500
      }
    }, p.label)), /*#__PURE__*/React.createElement("div", {
      className: "mono tnum",
      style: {
        color: p.value < 0 ? '#f87171' : p.color,
        fontSize: 15,
        fontWeight: 600
      }
    }, p.value >= 0 ? '+' : '', fmt(p.value))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 6,
        height: 28
      }
    }, /*#__PURE__*/React.createElement(Sparkline, {
      data: p.data,
      color: p.color,
      width: 900,
      height: 28,
      dot: false,
      fill: true,
      stretch: true
    })))))), scene === 2 && /*#__PURE__*/React.createElement("div", {
      style: {
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(255,255,255,0.015)',
        padding: '10px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 10,
        color: 'rgba(255,255,255,0.55)',
        letterSpacing: '0.18em',
        marginBottom: 8
      }
    }, "TOP MOVERS \xB7 BY VIEW DELTA"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 8
      }
    }, mobileTopMovers.map((a, i) => /*#__PURE__*/React.createElement("div", {
      key: a.id || `${a.platform}:${a.username || a.handle}`,
      style: {
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.07)',
        background: 'rgba(255,255,255,0.01)',
        padding: '8px 9px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono tnum",
      style: {
        fontSize: 13,
        color: 'rgba(255,255,255,0.5)',
        minWidth: 18
      }
    }, i + 1), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, _tvBroadcastAccountTitle(a))), /*#__PURE__*/React.createElement("span", {
      className: "mono tnum",
      style: {
        fontSize: 15,
        fontWeight: 600,
        color: '#4ade80'
      }
    }, _hasDelta(a.dViews) ? `+${fmt(a.dViews)}` : '0')), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        marginTop: 4,
        fontSize: 10,
        color: 'rgba(255,255,255,0.46)',
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(PlatformGlyph, {
      id: a.platform,
      size: 11
    }), /*#__PURE__*/React.createElement("span", null, (PLATFORM_META[a.platform]?.label || a.platform || '').toUpperCase()), /*#__PURE__*/React.createElement("span", {
      style: {
        width: 3,
        height: 3,
        borderRadius: 999,
        background: 'rgba(255,255,255,0.35)'
      }
    }), /*#__PURE__*/React.createElement("span", null, PROFILE_META[a.profile]?.label || 'Без профиля'), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto'
      }
    }, "VIEWS ", fmt(a.views))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 7,
        height: 6,
        borderRadius: 999,
        background: 'rgba(255,255,255,0.06)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${Math.min(100, Number(a.dViews || 0) / mobileTopMax * 100)}%`,
        height: '100%',
        background: moodTone.accent
      }
    }))))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 10,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.07)',
        background: 'rgba(255,255,255,0.01)',
        padding: '8px 9px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 9,
        color: 'rgba(255,255,255,0.5)',
        letterSpacing: '0.14em',
        marginBottom: 6
      }
    }, "BY PROFILE"), (PROFILES || []).slice(0, 3).map(p => /*#__PURE__*/React.createElement("div", {
      key: `m-prof-${p.id}`,
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        gap: 6,
        alignItems: 'center',
        marginBottom: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: 'rgba(255,255,255,0.85)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, p.label), /*#__PURE__*/React.createElement("span", {
      className: "mono tnum",
      style: {
        fontSize: 12,
        color: p.color
      }
    }, fmt(Number(p.accounts || 0)))))), /*#__PURE__*/React.createElement("div", {
      style: {
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.07)',
        background: 'rgba(255,255,255,0.01)',
        padding: '8px 9px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 9,
        color: 'rgba(255,255,255,0.5)',
        letterSpacing: '0.14em',
        marginBottom: 6
      }
    }, "PLATFORMS"), (PLATFORMS || []).slice(0, 4).map(p => /*#__PURE__*/React.createElement("div", {
      key: `m-plat-${p.id}`,
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        gap: 6,
        alignItems: 'center',
        marginBottom: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: 'rgba(255,255,255,0.85)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, p.label), /*#__PURE__*/React.createElement("span", {
      className: "mono tnum",
      style: {
        fontSize: 12,
        color: p.color
      }
    }, fmt(Number(p.accounts || 0))))))))), /*#__PURE__*/React.createElement(TVSceneIndicator, {
      total: SCENES.length,
      current: scene,
      accent: moodTone.accent,
      onSelect: i => setScene(i),
      autoPaused: sceneAutoPaused,
      setAutoPaused: setSceneAutoPaused
    })));
  }
  return /*#__PURE__*/React.createElement("div", {
    onWheel: onDesktopWheel,
    style: {
      position: 'fixed',
      inset: 0,
      background: moodTone.bg,
      color: '#fff',
      overflow: 'hidden',
      fontFamily: 'Space Grotesk, sans-serif'
    },
    "data-screen-label": "TV Broadcast"
  }, /*#__PURE__*/React.createElement(ParticleField, {
    count: mood === 'calm' ? 80 : 50,
    color: moodTone.accent,
    opacity: mood === 'bloomberg' ? 0.25 : 0.6
  }), /*#__PURE__*/React.createElement(AtomicGrid, {
    opacity: mood === 'bloomberg' ? 0.025 : 0.04,
    size: 64
  }), /*#__PURE__*/React.createElement(TVHeader, {
    now: now,
    accent: moodTone.accent,
    mood: mood,
    onExit: onExit,
    autoScheduleLabel: TV_AUTO_SCHEDULE_LABEL,
    autoIsRunning: autoRunning
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 110,
      left: 0,
      right: 0,
      bottom: 110
    }
  }, /*#__PURE__*/React.createElement(SceneSwitch, {
    scene: SCENES[scene],
    accent: moodTone.accent,
    mood: mood,
    pulse: pulse
  })), /*#__PURE__*/React.createElement(TVTicker, {
    accent: moodTone.accent
  }), /*#__PURE__*/React.createElement(TVSceneIndicator, {
    total: SCENES.length,
    current: scene,
    accent: moodTone.accent,
    onSelect: i => setScene(i),
    autoPaused: sceneAutoPaused,
    setAutoPaused: setSceneAutoPaused
  }));
}

// ── Header: brand, time, autoupdate state ──────────────────
function TVHeader({
  now,
  accent,
  mood,
  onExit,
  autoScheduleLabel,
  autoIsRunning = false
}) {
  const isMobile = useIsMobile(980);
  const t = now.toTimeString().slice(0, 8);
  const d = now.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: 'long',
    weekday: 'long'
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      padding: isMobile ? '10px 10px' : '32px 56px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      zIndex: 10,
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: isMobile ? 17 : 26,
      fontWeight: 600,
      letterSpacing: '-0.01em',
      lineHeight: 1.05
    }
  }, "AccountsStats ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: accent
    }
  }, "/"), " Live"), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: isMobile ? 9 : 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.16em',
      textTransform: 'uppercase',
      marginTop: 2
    }
  }, "BROADCAST \xB7 ", TOTAL.accounts || 0, " ACCOUNTS"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: isMobile ? 10 : 32
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 9,
      height: 9,
      minWidth: 9,
      minHeight: 9,
      borderRadius: '50%',
      background: autoIsRunning ? '#4ade80' : accent,
      boxShadow: `0 0 14px ${autoIsRunning ? '#4ade80' : accent}`,
      display: 'inline-block',
      flexShrink: 0,
      aspectRatio: '1 / 1'
    },
    className: "pulse-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 13,
      color: 'rgba(255,255,255,0.7)',
      letterSpacing: '0.2em'
    }
  }, "AUTO \xB7 ", autoScheduleLabel || '—')), !isMobile && /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 30,
      fontWeight: 500,
      color: '#fff',
      letterSpacing: '0.02em'
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'rgba(255,255,255,0.4)',
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      marginTop: 2
    }
  }, d, " \xB7 MSK")), /*#__PURE__*/React.createElement("button", {
    onClick: onExit,
    style: {
      padding: isMobile ? '8px 10px' : '10px 18px',
      borderRadius: 999,
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.1)',
      color: 'rgba(255,255,255,0.7)',
      fontSize: isMobile ? 11 : 12,
      letterSpacing: isMobile ? '0.08em' : '0.16em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      fontFamily: 'JetBrains Mono, monospace'
    }
  }, isMobile ? 'EXIT' : 'Exit TV')), /*#__PURE__*/React.createElement("style", null, `
        .pulse-dot { animation: pulseDot 1.6s ease-in-out infinite; }
        @keyframes pulseDot { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.7); } }
      `));
}
function AtomLogo({
  size = 44,
  accent = '#6aa9ff'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 100 100",
    width: size,
    height: size
  }, /*#__PURE__*/React.createElement("ellipse", {
    cx: "50",
    cy: "50",
    rx: "42",
    ry: "16",
    fill: "none",
    stroke: accent,
    strokeWidth: "1.5",
    opacity: "0.7"
  }), /*#__PURE__*/React.createElement("ellipse", {
    cx: "50",
    cy: "50",
    rx: "42",
    ry: "16",
    fill: "none",
    stroke: accent,
    strokeWidth: "1.5",
    opacity: "0.7",
    transform: "rotate(60 50 50)"
  }), /*#__PURE__*/React.createElement("ellipse", {
    cx: "50",
    cy: "50",
    rx: "42",
    ry: "16",
    fill: "none",
    stroke: accent,
    strokeWidth: "1.5",
    opacity: "0.7",
    transform: "rotate(-60 50 50)"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "50",
    cy: "50",
    r: "6",
    fill: accent
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "50",
    cy: "50",
    r: "3",
    fill: "#fff"
  }));
}

// ── Scene switcher ─────────────────────────────────────────
function SceneSwitch({
  scene,
  accent,
  mood,
  pulse
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: '100%',
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    key: scene,
    style: {
      position: 'absolute',
      inset: 0,
      animation: 'sceneIn .63s ease-out'
    }
  }, scene === 'atom' && /*#__PURE__*/React.createElement(SceneAtom, {
    accent: accent,
    mood: mood
  }), scene === 'pulse' && /*#__PURE__*/React.createElement(ScenePulse, {
    accent: accent,
    mood: mood,
    pulse: pulse
  }), scene === 'top' && /*#__PURE__*/React.createElement(SceneTop, {
    accent: accent,
    mood: mood
  })), /*#__PURE__*/React.createElement("style", null, `
        @keyframes sceneIn { from { opacity: 0; } to { opacity: 1; } }
      `));
}

// ── SCENE 1: Hero atom + 4 totals around ───────────────────
function SceneAtom({
  accent,
  mood
}) {
  const orbits = [{
    rx: 220,
    ry: 80,
    rot: 0,
    color: '#4ade80',
    opacity: 0.5,
    dur: 32,
    particleR: 9
  }, {
    rx: 220,
    ry: 80,
    rot: 60,
    color: '#ec4899',
    opacity: 0.5,
    dur: 26,
    particleR: 8
  }, {
    rx: 220,
    ry: 80,
    rot: -60,
    color: '#f59e0b',
    opacity: 0.5,
    dur: 38,
    particleR: 7
  }, {
    rx: 290,
    ry: 110,
    rot: 30,
    color: accent,
    opacity: 0.3,
    dur: 48,
    particleR: 5,
    dash: '2 8'
  }];
  const items = [{
    label: 'ПОДПИСЧИКИ',
    value: TOTAL.followers.value,
    delta: TOTAL.followers.delta,
    color: '#4ade80',
    spark: _buildYesterdayBaselineSpark(TOTAL.followers.delta, TOTAL.followers.yesterdayDelta, 24, 10),
    infoTitle: 'Подписчики',
    infoText: 'Мини-график: сравнение дельты за 24h с календарным вчера (дневные дельты по снимкам из API). Ось условная 0…10; при отсутствии вчерашних данных используется запасной режим.'
  }, {
    label: 'ПРОСМОТРЫ',
    value: TOTAL.views.value,
    delta: TOTAL.views.delta,
    color: '#ec4899',
    spark: _buildYesterdayBaselineSpark(TOTAL.views.delta, TOTAL.views.yesterdayDelta, 24, 10),
    infoTitle: 'Просмотры',
    infoText: 'Мини-график: дельта просмотров за 24h относительно календарного вчера (снимки). Ось условная 0…10.'
  }, {
    label: 'ЛАЙКИ',
    value: TOTAL.likes.value,
    delta: TOTAL.likes.delta,
    color: '#f59e0b',
    spark: _buildYesterdayBaselineSpark(TOTAL.likes.delta, TOTAL.likes.yesterdayDelta, 24, 10),
    infoTitle: 'Лайки',
    infoText: 'Мини-график: дельта лайков за 24h и календарный вчера (снимки). Ось условная 0…10.'
  }, {
    label: 'ПУБЛИКАЦИИ',
    value: TOTAL.posts.value,
    delta: TOTAL.posts.delta,
    color: accent,
    spark: _buildYesterdayBaselineSpark(TOTAL.posts.delta, TOTAL.posts.yesterdayDelta, 24, 10),
    infoTitle: 'Публикации',
    infoText: 'Мини-график: дельта публикаций за 24h и календарный вчера (снимки). Ось условная 0…10.'
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      height: '100%',
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gridTemplateRows: '1fr 1fr',
      gap: 28,
      padding: '0 56px'
    }
  }, /*#__PURE__*/React.createElement(BigStat, _extends({}, items[0], {
    align: "left"
  })), /*#__PURE__*/React.createElement(BigStat, _extends({}, items[1], {
    align: "left"
  })), /*#__PURE__*/React.createElement(BigStat, _extends({}, items[2], {
    align: "left"
  })), /*#__PURE__*/React.createElement(BigStat, _extends({}, items[3], {
    align: "left"
  })));
}
function BigStat({
  label,
  value,
  delta,
  color,
  spark,
  align,
  infoTitle,
  infoText
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      padding: '36px 44px 28px',
      borderRadius: 20,
      background: 'linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.005))',
      border: '1px solid rgba(255,255,255,0.06)',
      textAlign: 'left',
      position: 'relative',
      overflow: 'hidden',
      minWidth: 0,
      minHeight: 0
    }
  }, infoText && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 10,
      right: 10,
      zIndex: 2
    }
  }, /*#__PURE__*/React.createElement(InfoButton, {
    onClick: () => uiAlert(infoText, infoTitle || 'Подробнее'),
    title: `Подробнее: ${label}`,
    size: 11
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      width: 4,
      bottom: 0,
      background: color,
      opacity: 0.55
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      color: 'rgba(255,255,255,0.7)',
      fontWeight: 500,
      textTransform: 'capitalize'
    }
  }, label.toLowerCase()), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 13,
      color: 'rgba(255,255,255,0.4)',
      letterSpacing: '0.16em'
    }
  }, "24H")), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      fontSize: 'clamp(80px, 11vw, 168px)',
      fontWeight: 700,
      color: '#fff',
      lineHeight: 0.9,
      letterSpacing: '-0.04em',
      marginTop: 12
    }
  }, fmt(value)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-end',
      gap: 18,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 28,
      color: color,
      fontWeight: 500,
      whiteSpace: 'nowrap'
    }
  }, "\u25B2 +", Number(delta) > 0 ? fmt(delta) : '0'), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 112,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(ResponsiveSpark, {
    data: spark,
    color: color,
    scaleMin: 0,
    scaleMax: 10
  }))));
}
function _buildPercentCappedSpark(total, delta, points = 24, capPercent = 10) {
  const n = Math.max(2, Number(points || 24));
  const totalNum = Number(total || 0);
  const deltaNum = Number(delta || 0);
  // Growth must be measured from previous value, not from current total:
  // prev=117 -> now=176, +59 means ~50% growth (not ~33%).
  const prev = Math.max(1, totalNum - deltaNum);
  const rawPercent = Math.max(0, deltaNum) / prev * 100;
  const target = Math.min(Math.max(0, rawPercent), capPercent);
  const out = [];
  const isCappedMax = target >= capPercent * 0.98;
  for (let i = 0; i < n; i += 1) {
    const t = i / (n - 1);
    if (isCappedMax) {
      // If growth hit/exceeded cap (>=10%), keep trajectory visually near the top.
      const topBandStart = capPercent * 0.72;
      const easedTop = 1 - Math.pow(1 - t, 0.72);
      const waveTop = Math.sin(i * 0.45) * Math.max(0.02, capPercent * 0.018);
      out.push(Math.max(0, Math.min(capPercent, topBandStart + (capPercent - topBandStart) * easedTop + waveTop)));
    } else {
      const eased = 1 - Math.pow(1 - t, 1.25);
      const wave = Math.sin(i * 0.5) * Math.max(0.03, target * 0.03);
      out.push(Math.max(0, Math.min(capPercent, target * eased + wave)));
    }
  }
  for (let i = 1; i < out.length; i += 1) {
    if (out[i] < out[i - 1]) out[i] = out[i - 1];
  }
  // Ensure final point reflects exact capped percent target.
  out[out.length - 1] = target;
  return out;
}

/** Поля `yesterday_*_delta` из GET /api/accounts/summary/; null если с бэка пришло null/нет числа. */
function _parseSummaryYesterdayDelta(v) {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Мини-график TV (сцена 1): опорная дельта `yesterdayDelta` = 50% высоты при равенстве с сегодняшней; ≥2× опоры — верх. */
function _buildYesterdayBaselineSpark(todayDelta, yesterdayDelta, points = 24, scaleMax = 10) {
  const n = Math.max(2, Number(points || 24));
  const cap = Number(scaleMax) > 0 ? Number(scaleMax) : 10;
  const cur = Number(todayDelta ?? 0);
  const curPos = Math.max(0, cur);
  const hasY = yesterdayDelta !== null && yesterdayDelta !== undefined && Number.isFinite(Number(yesterdayDelta));
  if (!hasY) {
    const totalHint = Math.max(1, curPos) + curPos;
    return _buildPercentCappedSpark(totalHint, curPos, n, cap);
  }
  const ref = Math.max(1, Math.abs(Number(yesterdayDelta)));
  const endNorm = Math.min(1, curPos / (2 * ref));
  const target = endNorm * cap;
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const t = i / (n - 1);
    const eased = 1 - Math.pow(1 - t, 1.2);
    const wave = Math.sin(i * 0.5) * Math.max(0.04, target * 0.04);
    out.push(Math.max(0, Math.min(cap, target * eased + wave)));
  }
  for (let i = 1; i < out.length; i += 1) {
    if (out[i] < out[i - 1]) out[i] = out[i - 1];
  }
  out[out.length - 1] = target;
  return out;
}
function ResponsiveSpark({
  data,
  color,
  scaleMin,
  scaleMax
}) {
  const w = 600,
    h = 60;
  const max = Number.isFinite(scaleMax) ? Number(scaleMax) : Math.max(...data);
  const min = Number.isFinite(scaleMin) ? Number(scaleMin) : Math.min(...data);
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - (v - min) / (max - min || 1) * (h - 8) - 4]);
  const path = pts.map((p, i) => i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`).join(' ');
  const area = `${path} L${w},${h} L0,${h} Z`;
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${w} ${h}`,
    preserveAspectRatio: "none",
    style: {
      width: '100%',
      height: '100%',
      overflow: 'visible'
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: `sf-${color.replace('#', '')}`,
    x1: "0",
    x2: "0",
    y1: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0%",
    stopColor: color,
    stopOpacity: "0.4"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "100%",
    stopColor: color,
    stopOpacity: "0"
  }))), /*#__PURE__*/React.createElement("path", {
    d: area,
    fill: `url(#sf-${color.replace('#', '')})`
  }), /*#__PURE__*/React.createElement("path", {
    d: path,
    fill: "none",
    stroke: color,
    strokeWidth: "2.4",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    vectorEffect: "non-scaling-stroke"
  }));
}

// ── SCENE 2: Pulse / dynamics — sparklines per platform & profile ──
function ScenePulse({
  accent,
  mood,
  pulse
}) {
  const isMobile = useIsMobile(980);
  const [infoPopover, setInfoPopover] = React.useState(null); // {title, text, left, top}
  const openInfoPopover = (event, title, text) => {
    const rect = event?.currentTarget?.getBoundingClientRect?.();
    const popW = 320;
    const margin = 12;
    const vw = window.innerWidth || 1280;
    const vh = window.innerHeight || 720;
    const defaultLeft = rect ? rect.left + rect.width - popW : vw - popW - margin;
    const left = Math.max(margin, Math.min(vw - popW - margin, defaultLeft));
    const desiredTop = rect ? rect.bottom + 8 : 64;
    const top = Math.max(margin, Math.min(vh - 170, desiredTop));
    setInfoPopover({
      title,
      text,
      left,
      top
    });
  };
  const showMainInfo = e => openInfoPopover(e, 'Что показывает график', 'Суммарные просмотры за последние 24 ч: одна точка = один час (последнее значение в часе). До «сейчас» линия дотягивается по актуальному TOTAL из summary.');
  const showPlatformInfo = (e, label) => openInfoPopover(e, `Platform Pulse · ${label}`, `Линия ${label} показывает изменение дельты просмотров платформы между точками автообновления. Число справа — суммарный вклад платформы за интервал.`);
  const seriesAll = Array.isArray(AUTO_REFRESH_SERIES) ? AUTO_REFRESH_SERIES : [];
  const nowTs = Date.now();
  const seriesPast = seriesAll.filter(p => {
    const ts = Date.parse(String(p?.measured_at || ''));
    return Number.isFinite(ts) && ts <= nowTs;
  });
  // Ignore future points so the right edge reflects the last completed refresh.
  const seriesRaw = seriesPast.length > 0 ? seriesPast : seriesAll;
  const series = _aggregateSeriesByHour(seriesRaw, nowTs, 24);
  const seriesHasData = series.length > 0;
  const lastPoint = seriesHasData ? series[series.length - 1] : null;
  const liveViewsTotal = Number(TOTAL.views.value || 0);
  const lastSnapTotal = Number(lastPoint?.view_count_total || 0);
  const baseDayDeltaFromPoints = Number(lastPoint?.view_delta_from_day_start || 0);
  // AutoRefreshPoint только после полного автообновления; ручные refresh не дают новых точек —
  // добиваем прирост до актуального TOTAL из summary (тот же источник, что и карточки).
  const dayDeltaViews = seriesHasData && lastPoint ? baseDayDeltaFromPoints + (liveViewsTotal - lastSnapTotal) : Number(TOTAL.views.delta || 0);
  const latestTotalViews = Math.max(lastSnapTotal, liveViewsTotal);
  const dayStartViews = Math.max(0, latestTotalViews - dayDeltaViews);
  const dayGrowthPercent = dayStartViews > 0 ? dayDeltaViews / dayStartViews * 100 : 0;
  let peakLabel = '—';
  let troughLabel = '—';
  let avgLabel = '—';
  if (seriesHasData) {
    const statsSeries = series.filter(p => String(p?.source || '') !== 'anchor');
    const use = statsSeries.length > 0 ? statsSeries : series;
    let peak = use[0];
    let trough = use[0];
    let sum = 0;
    for (const p of use) {
      const d = Number(p?.view_delta_from_prev_point || 0);
      sum += d;
      if (d > Number(peak?.view_delta_from_prev_point || 0)) peak = p;
      if (d < Number(trough?.view_delta_from_prev_point || 0)) trough = p;
    }
    peakLabel = String(peak?.slot_label || _ruShortDate(peak?.measured_at || ''));
    troughLabel = String(trough?.slot_label || _ruShortDate(trough?.measured_at || ''));
    avgLabel = fmt(Math.round(sum / Math.max(1, use.length)));
  } else {
    avgLabel = fmt(Math.round(Number(TOTAL.views.delta || 0) / 24));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      height: '100%',
      padding: '0 56px',
      display: 'grid',
      gridTemplateColumns: '1.4fr 1fr',
      gap: 28
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 20,
      border: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(255,255,255,0.015)',
      padding: 32,
      display: 'flex',
      flexDirection: 'column',
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 12,
      right: 12,
      zIndex: 3
    }
  }, /*#__PURE__*/React.createElement(InfoButton, {
    onClick: showMainInfo,
    title: "\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435 \u043E \u0433\u0440\u0430\u0444\u0438\u043A\u0435",
    size: 12
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em'
    }
  }, "VIEWS \xB7 LAST 24H"), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: 88,
      fontWeight: 700,
      marginTop: 8,
      lineHeight: 0.95,
      letterSpacing: '-0.03em'
    }
  }, fmtSign(dayDeltaViews)), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 16,
      color: dayGrowthPercent >= 0 ? '#4ade80' : '#f87171',
      marginTop: 6
    }
  }, `${dayGrowthPercent >= 0 ? '▲' : '▼'} ${Math.abs(dayGrowthPercent).toFixed(1)}% vs start of day`)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 24
    }
  }, [{
    k: 'PEAK',
    v: peakLabel,
    c: accent
  }, {
    k: 'TROUGH',
    v: troughLabel,
    c: 'rgba(255,255,255,0.4)'
  }, {
    k: 'AVG/POINT',
    v: avgLabel,
    c: '#4ade80'
  }].map(s => /*#__PURE__*/React.createElement("div", {
    key: s.k,
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'rgba(255,255,255,0.4)',
      letterSpacing: '0.24em'
    }
  }, s.k), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: 22,
      fontWeight: 600,
      color: s.c,
      marginTop: 2
    }
  }, s.v))))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      marginTop: 24,
      position: 'relative',
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement(BigChart, {
    accent: accent,
    series: series
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em',
      marginBottom: 4
    }
  }, "PLATFORM PULSE"), (() => {
    const candidates = (PLATFORMS || []).map((p, i) => {
      const pulse = _platformPulseFromSeries(series, p.id);
      const hasReal = Array.isArray(pulse.data) && pulse.data.length > 1 && pulse.hasVariation;
      const fallbackValue = Math.round(TOTAL.views.delta * p.share);
      return {
        id: p.id,
        label: p.label,
        color: p.color,
        idx: i,
        hasReal,
        value: hasReal ? Math.round(pulse.totalDelta) : fallbackValue,
        data: hasReal ? _normalizeSparkData(pulse.data) : _normalizeSparkData(TREND_24H.map((v, idx) => v * (p.share + 0.4) + Math.sin(idx + i) * 30))
      };
    });
    const hasAnyReal = candidates.some(c => c.hasReal);
    const rows = hasAnyReal ? candidates.filter(c => c.hasReal).sort((a, b) => Math.abs(Number(b.value || 0)) - Math.abs(Number(a.value || 0))).slice(0, 5) : candidates.slice(0, 5);
    return rows.map(p => {
      const value = Number(p.value || 0);
      const data = p.data;
      return /*#__PURE__*/React.createElement("div", {
        key: p.id,
        style: {
          position: 'relative',
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr auto' : '160px minmax(0, 1fr) 110px',
          alignItems: 'center',
          gap: isMobile ? 6 : 12,
          padding: isMobile ? '10px 10px' : '12px 16px',
          borderRadius: 14,
          background: 'rgba(255,255,255,0.015)',
          border: '1px solid rgba(255,255,255,0.05)'
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          minWidth: 0
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 8,
          height: 8,
          borderRadius: 999,
          background: p.color,
          boxShadow: `0 0 10px ${p.color}`
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: isMobile ? 14 : 15,
          fontWeight: 500,
          whiteSpace: isMobile ? 'nowrap' : 'normal',
          overflow: isMobile ? 'hidden' : 'visible',
          textOverflow: isMobile ? 'ellipsis' : 'clip'
        }
      }, p.label), !isMobile && /*#__PURE__*/React.createElement(InfoButton, {
        onClick: e => showPlatformInfo(e, p.label),
        title: `Подробнее о ${p.label}`,
        size: 10
      })), /*#__PURE__*/React.createElement("div", {
        style: {
          height: 32,
          width: '100%',
          minWidth: 0,
          gridColumn: isMobile ? '1 / -1' : 'auto'
        }
      }, /*#__PURE__*/React.createElement(Sparkline, {
        data: data,
        color: p.color,
        width: 1200,
        height: 32,
        dot: false,
        fill: true,
        stretch: true
      })), /*#__PURE__*/React.createElement("div", {
        className: "mono tnum",
        style: {
          fontSize: isMobile ? 16 : 18,
          color: value < 0 ? '#f87171' : p.color,
          textAlign: 'right',
          fontWeight: 600
        }
      }, value >= 0 ? '+' : '', fmt(value)));
    });
  })()), infoPopover && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
    onClick: () => setInfoPopover(null),
    "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C \u043E\u043F\u0438\u0441\u0430\u043D\u0438\u0435",
    style: {
      position: 'fixed',
      inset: 0,
      border: 'none',
      background: 'transparent',
      padding: 0,
      margin: 0,
      zIndex: 120,
      cursor: 'default'
    }
  }), /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-label": infoPopover.title,
    style: {
      position: 'fixed',
      left: infoPopover.left,
      top: infoPopover.top,
      width: 320,
      maxWidth: 'calc(100vw - 24px)',
      borderRadius: 10,
      border: '1px solid rgba(148,163,184,0.35)',
      background: 'rgba(15,23,42,0.96)',
      color: '#e2e8f0',
      padding: '10px 12px',
      zIndex: 121,
      boxShadow: '0 12px 24px rgba(0,0,0,0.35)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: '#cbd5e1',
      letterSpacing: '0.08em',
      marginBottom: 6
    }
  }, infoPopover.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      lineHeight: 1.45,
      color: '#cbd5e1'
    }
  }, infoPopover.text))));
}
function BigChart({
  accent,
  series = [],
  isMobile = false
}) {
  const w = 800,
    h = 320;
  const nowTs = Date.now();
  const windowMs = 24 * 60 * 60 * 1000;
  const windowStart = nowTs - windowMs;
  const windowEnd = nowTs;
  // Небольшой допуск: якорь с сервера (rolling 24h) может оказаться на доли минуты левее окна из‑за рассинхрона часов.
  const windowSlackMs = 120000;
  const seriesInWindow = _aggregateSeriesByHour((Array.isArray(series) ? series : []).filter(p => {
    const ts = Date.parse(String(p?.measured_at || ''));
    return Number.isFinite(ts) && ts <= windowEnd + 60000;
  }), windowEnd, 24);
  const liveViewsTotal = Number(typeof TOTAL !== 'undefined' && TOTAL?.views ? TOTAL.views.value : 0) || 0;
  const lastSnap = seriesInWindow.length > 0 ? seriesInWindow[seriesInWindow.length - 1] : null;
  const dayDeltaForChart = lastSnap ? Number(lastSnap.view_delta_from_day_start || 0) + (liveViewsTotal - Number(lastSnap.view_count_total || 0)) : Number(typeof TOTAL !== 'undefined' && TOTAL?.views ? TOTAL.views.delta : 0) || 0;
  const displayTotals = _displayTotalsForChart(seriesInWindow, liveViewsTotal, dayDeltaForChart);
  const realPoints = seriesInWindow.map((p, i) => ({
    ts: Date.parse(String(p?.measured_at || '')),
    value: displayTotals ? Number(displayTotals[i] || 0) : Number(p?.view_count_total || 0)
  })).filter(p => Number.isFinite(p.ts) && Number.isFinite(p.value));
  const hasRealSeries = realPoints.length >= 1;
  let points = [];
  let xTicks = [];
  const _buildSixHourTicksInWindow = (startTs, endTs) => {
    const start = new Date(startTs);
    const end = new Date(endTs);
    const first = new Date(start);
    first.setMinutes(0, 0, 0);
    first.setHours(Math.ceil(first.getHours() / 6) * 6, 0, 0, 0);
    const out = [];
    for (let t = first.getTime(); t <= end.getTime(); t += 6 * 60 * 60 * 1000) out.push(t);
    return out;
  };
  if (hasRealSeries) {
    const drawnPoints = [...realPoints];
    const last = drawnPoints[drawnPoints.length - 1];
    // До «сейчас» тянем линию: если после последней точки автообновления шли ручные refresh,
    // берём актуальный TOTAL.views из summary, иначе остаётся плато на last.value.
    if (last && last.ts < windowEnd) {
      let endVal = last.value;
      try {
        const lv = Number(typeof TOTAL !== 'undefined' && TOTAL && TOTAL.views ? TOTAL.views.value : NaN);
        if (Number.isFinite(lv)) endVal = Math.max(last.value, lv);
      } catch (_) {/* ignore */}
      drawnPoints.push({
        ts: windowEnd,
        value: endVal
      });
    }
    for (let i = 1; i < drawnPoints.length; i += 1) {
      if (drawnPoints[i].value < drawnPoints[i - 1].value) {
        drawnPoints[i].value = drawnPoints[i - 1].value;
      }
    }
    const minV = Math.min(...drawnPoints.map(p => p.value));
    const maxV = Math.max(...drawnPoints.map(p => p.value));
    const valueRange = Math.max(1, maxV - minV);
    // Keep chart from looking like it starts at absolute zero.
    const padDown = Math.max(120, Math.round(valueRange * 0.18));
    const padUp = Math.max(80, Math.round(valueRange * 0.12));
    const scaleMin = Math.max(0, minV - padDown);
    const scaleMax = maxV + padUp;
    points = drawnPoints.map(p => {
      const x = Math.max(0, Math.min(w, (p.ts - windowStart) / (windowEnd - windowStart || 1) * w));
      const y = h - (p.value - scaleMin) / (scaleMax - scaleMin || 1) * (h - 30) - 10;
      return [x, y, p.ts, p.value];
    });
    xTicks = _buildSixHourTicksInWindow(windowStart, windowEnd);
  } else {
    const data = TREND_24H;
    const max = Math.max(1, ...data);
    const stepX = w / (data.length - 1);
    points = data.map((v, i) => [i * stepX, h - v / max * (h - 30) - 10, null, v]);
    xTicks = _buildSixHourTicksInWindow(windowStart, windowEnd);
  }
  const path = points.map((p, i) => i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`).join(' ');
  const areaPath = path ? `${path} L${w},${h} L0,${h} Z` : '';
  const fmtTime = ts => new Date(ts).toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit'
  });
  const fmtDate = ts => new Date(ts).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit'
  });
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${w} ${h}`,
    preserveAspectRatio: "none",
    style: {
      width: '100%',
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "bigfill",
    x1: "0",
    x2: "0",
    y1: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0%",
    stopColor: accent,
    stopOpacity: "0.5"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "100%",
    stopColor: accent,
    stopOpacity: "0"
  }))), [0.25, 0.5, 0.75].map(y => /*#__PURE__*/React.createElement("line", {
    key: y,
    x1: "0",
    x2: w,
    y1: h * y,
    y2: h * y,
    stroke: "rgba(255,255,255,0.05)",
    strokeDasharray: "2 6"
  })), xTicks.map((ts, i) => {
    const x = (ts - windowStart) / (windowEnd - windowStart || 1) * w;
    return /*#__PURE__*/React.createElement("g", {
      key: `${ts}-${i}`,
      transform: `translate(${x}, ${h - 16})`
    }, /*#__PURE__*/React.createElement("text", {
      x: "0",
      y: "0",
      fill: isMobile ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.34)",
      fontSize: isMobile ? "14.4" : "10",
      textAnchor: i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle',
      fontFamily: "JetBrains Mono, monospace"
    }, fmtTime(ts)), /*#__PURE__*/React.createElement("text", {
      x: "0",
      y: "11",
      fill: isMobile ? "rgba(255,255,255,0.82)" : "rgba(255,255,255,0.24)",
      fontSize: "9",
      textAnchor: i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle',
      fontFamily: "JetBrains Mono, monospace"
    }, fmtDate(ts)));
  }), /*#__PURE__*/React.createElement("path", {
    d: areaPath,
    fill: "url(#bigfill)"
  }), /*#__PURE__*/React.createElement("path", {
    d: path,
    fill: "none",
    stroke: accent,
    strokeWidth: "2.4",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: points[points.length - 1][0],
    cy: points[points.length - 1][1],
    r: "6",
    fill: accent,
    stroke: "#050608",
    strokeWidth: "3"
  }, /*#__PURE__*/React.createElement("animate", {
    attributeName: "r",
    values: "6;9;6",
    dur: "1.6s",
    repeatCount: "indefinite"
  })));
}

// ── SCENE 3: Top accounts leaderboard ──────────────────────
const TV_CLICKS_COLOR = '#a78bfa';
function TvTopLeaderboardRow({
  a,
  i,
  rankAccent,
  maxDelta,
  totalValue,
  deltaValue,
  deltaColor,
  barMetric
}) {
  const barPct = maxDelta > 0 ? Number(barMetric || 0) / maxDelta * 100 : 0;
  const meta = PLATFORM_META[a.platform] || {
    color: '#9ca3af',
    label: a.platform || 'Unknown'
  };
  const prof = PROFILE_META[a.profile] || {
    color: '#525a70',
    label: 'Без профиля'
  };
  const deltaNum = Number(deltaValue || 0);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      padding: '11px 16px',
      borderRadius: 14,
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.05)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: `linear-gradient(90deg, ${prof.color}22, transparent ${Math.min(95, barPct + 20)}%)`,
      opacity: 0.7
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      display: 'grid',
      gridTemplateColumns: '32px 44px 1fr auto auto',
      alignItems: 'center',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 20,
      fontWeight: 700,
      color: i < 3 ? rankAccent : 'rgba(255,255,255,0.45)'
    }
  }, String(i + 1).padStart(2, '0')), /*#__PURE__*/React.createElement(AccountAvatar, {
    src: a.avatarUrl,
    name: a.name,
    size: 40,
    borderColor: `${meta.color}55`,
    fallbackBg: `linear-gradient(135deg, ${meta.color}55, ${prof.color}40)`
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 17,
      fontWeight: 500,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, _tvBroadcastAccountTitle(a)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginTop: 3,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 10,
      color: meta.color,
      letterSpacing: '0.1em',
      textTransform: 'uppercase'
    }
  }, meta.label), /*#__PURE__*/React.createElement("span", {
    style: {
      width: 3,
      height: 3,
      borderRadius: 999,
      background: 'rgba(255,255,255,0.3)'
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 10,
      color: prof.color,
      letterSpacing: '0.1em'
    }
  }, prof.label))), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 16,
      color: 'rgba(255,255,255,0.65)',
      textAlign: 'right',
      minWidth: 56
    }
  }, fmt(totalValue)), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 20,
      color: deltaColor,
      fontWeight: 600,
      textAlign: 'right',
      minWidth: 80
    }
  }, _hasDelta(deltaNum) ? `${deltaNum >= 0 ? '+' : ''}${fmt(deltaNum)}` : '0')));
}
function TvTopLeaderboardBlock({
  title,
  rows,
  rankAccent,
  maxDelta,
  getTotal,
  getDelta,
  getBarMetric,
  deltaColor
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em',
      marginBottom: 12
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, rows.map((a, i) => /*#__PURE__*/React.createElement(TvTopLeaderboardRow, {
    key: `${a.id || a.handle}-${title}`,
    a: a,
    i: i,
    rankAccent: rankAccent,
    maxDelta: maxDelta,
    totalValue: getTotal(a),
    deltaValue: getDelta(a),
    deltaColor: deltaColor,
    barMetric: getBarMetric(a)
  }))));
}
function _tvClicksStackParts(clicks, dClicks) {
  const total = Math.max(0, Number(clicks || 0));
  if (total <= 0) return null;
  const delta = Number(dClicks || 0);
  if (delta <= 0) return {
    total,
    base: total,
    growth: 0
  };
  const growth = Math.min(delta, total);
  return {
    total,
    base: total - growth,
    growth
  };
}
function _parsePlatformColorRgb(color) {
  const c = String(color || '').trim();
  let m = /^#([0-9a-f]{6})$/i.exec(c);
  if (m) {
    const n = parseInt(m[1], 16);
    return {
      r: n >> 16 & 255,
      g: n >> 8 & 255,
      b: n & 255
    };
  }
  m = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i.exec(c);
  if (m) return {
    r: Number(m[1]),
    g: Number(m[2]),
    b: Number(m[3])
  };
  return null;
}

/** Сдвиг цвета платформы к малиново-пурпурному (синий + базовый оттенок). */
function _shiftPlatformColorToGrowthTint(color) {
  const rgb = _parsePlatformColorRgb(color);
  if (!rgb) return 'rgb(200, 60, 160)';
  const {
    r,
    g,
    b
  } = rgb;
  const nr = Math.min(255, Math.round(r * 0.9 + 28));
  const ng = Math.max(0, Math.round(g * 0.38 + 6));
  const nb = Math.min(255, Math.round(b * 0.72 + 118));
  return `rgb(${nr}, ${ng}, ${nb})`;
}

/** Прирост в CLICKS BY PLATFORM: TikTok — фиксированный, остальные — по оттенку платформы. */
const TV_CLICKS_GROWTH_BY_PLATFORM = {
  tiktok: 'rgb(255, 23, 77)'
};
function _growthBarColor(color, platformId) {
  const id = String(platformId || '').toLowerCase();
  const fixed = TV_CLICKS_GROWTH_BY_PLATFORM[id];
  if (fixed) return fixed;
  return _shiftPlatformColorToGrowthTint(color);
}
function _tvProfileDialGridLayout(count) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0) return { rows: [], staggerRowIdxes: [] };
  if (n <= 6) return { rows: [n], staggerRowIdxes: [] };
  if (n === 7) return { rows: [4, 3], staggerRowIdxes: [1] };
  if (n === 8) return { rows: [4, 4], staggerRowIdxes: [] };
  if (n === 9) return { rows: [3, 3, 3], staggerRowIdxes: [] };
  const rows = [];
  let left = n;
  while (left > 0) {
    rows.push(Math.min(4, left));
    left -= rows[rows.length - 1];
  }
  const maxCols = Math.max(...rows);
  const staggerRowIdxes = [];
  for (let i = 0; i < rows.length; i++) {
    if (rows[i] < maxCols) staggerRowIdxes.push(i);
  }
  return { rows, staggerRowIdxes };
}
let NF_TV_PROFILE_DIAL_W_CACHE = 0;
function _tvProfileDialGuessWidth(cols) {
  const c = Math.max(1, Math.floor(Number(cols) || 1));
  const vw = Math.max(320, Number(window.innerWidth) || 1200);
  const w = Math.floor(vw * 0.38);
  return _tvProfileDialMetrics(w, c).dialSize;
}
function _tvProfileDialEffectiveWidth(w) {
  const n = Math.max(0, Number(w) || 0);
  if (n > 0) {
    NF_TV_PROFILE_DIAL_W_CACHE = n;
    return n;
  }
  return NF_TV_PROFILE_DIAL_W_CACHE || 0;
}
function _tvProfileDialMetrics(containerW, cols) {
  const w = _tvProfileDialEffectiveWidth(containerW);
  const c = Math.max(1, Math.floor(Number(cols) || 1));
  if (w <= 0) {
    const dialSize = _tvProfileDialGuessWidth(c);
    return { dialSize, gap: Math.max(8, Math.floor(dialSize * 0.12)), edgePad: 10 };
  }
  const edgePad = Math.max(6, Math.floor(w * 0.02));
  const gapSlots = Math.max(0, c - 1);
  const gap = gapSlots > 0 ? Math.max(10, Math.floor((w * 0.08) / gapSlots)) : 0;
  const dialSize = Math.max(40, Math.floor((w - 2 * edgePad - gapSlots * gap) / c));
  return { dialSize, gap, edgePad };
}
function _tvProfileDialSize(containerW, cols) {
  return _tvProfileDialMetrics(containerW, cols).dialSize;
}
function TvProfileDialsGrid({ profiles, totalAccounts }) {
  const list = profiles || [];
  const layout = _tvProfileDialGridLayout(list.length);
  const maxCols = Math.max(1, ...(layout.rows.length ? layout.rows : [1]));
  const rootRef = React.useRef(null);
  const [containerW, setContainerW] = React.useState(() => NF_TV_PROFILE_DIAL_W_CACHE || 0);
  const effectiveW = _tvProfileDialEffectiveWidth(containerW);
  const maxDialInLayout = Math.max(
    ...layout.rows.map(cols => _tvProfileDialSize(effectiveW || _tvProfileDialGuessWidth(cols), cols)),
  );
  React.useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return undefined;
    const measure = () => {
      const w = Math.round(el.clientWidth || el.getBoundingClientRect().width || 0);
      if (w <= 0) return;
      const prev = NF_TV_PROFILE_DIAL_W_CACHE;
      if (prev > 0 && Math.abs(w - prev) < 3) return;
      NF_TV_PROFILE_DIAL_W_CACHE = w;
      setContainerW(w);
    };
    measure();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [list.length]);
  if (!list.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: { fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em' }
    }, "\u041D\u0435\u0442 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432 \u043F\u043E \u043F\u0440\u043E\u0444\u0438\u043B\u044F\u043C");
  }
  const rowGap = 8;
  let idx = 0;
  return /*#__PURE__*/React.createElement("div", {
    ref: rootRef,
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: rowGap,
      width: '100%',
      flex: 1,
      minHeight: maxDialInLayout + 28,
      overflow: 'hidden',
      boxSizing: 'border-box',
      padding: '2px 0'
    }
  }, layout.rows.map((cols, ri) => {
    const chunk = list.slice(idx, idx + cols);
    idx += cols;
    const met = _tvProfileDialMetrics(effectiveW, cols);
    const refMet = _tvProfileDialMetrics(effectiveW, maxCols);
    const stagger = layout.staggerRowIdxes.includes(ri) && cols < maxCols;
    const rowW = cols * met.dialSize + Math.max(0, cols - 1) * met.gap;
    const refRowW = maxCols * refMet.dialSize + Math.max(0, maxCols - 1) * refMet.gap;
    const offset = stagger ? Math.max(0, (refRowW - rowW) / 2) : 0;
    return /*#__PURE__*/React.createElement("div", {
      key: ri,
      style: {
        display: 'flex',
        flexDirection: 'row',
        justifyContent: 'flex-start',
        alignItems: 'center',
        width: '100%',
        boxSizing: 'border-box',
        paddingLeft: met.edgePad + offset,
        paddingRight: met.edgePad,
        gap: met.gap,
        flexShrink: 0
      }
    }, chunk.map(p => /*#__PURE__*/React.createElement("div", {
      key: p.id,
      style: {
        textAlign: 'center',
        flex: '0 0 auto',
        width: met.dialSize,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(RadialDial, {
      value: Math.min(1, Math.max(0, Number(p.accounts || 0) / totalAccounts)),
      size: met.dialSize,
      color: p.color,
      label: p.accounts,
      sub: p.label
    }))));
  }));
}
function SceneTop({
  accent
}) {
  const topViews = [...ACCOUNTS].sort((a, b) => Number(b.dViews || 0) - Number(a.dViews || 0)).slice(0, 5);
  const topClicks = [...ACCOUNTS].sort((a, b) => Number(b.dClicks || 0) - Number(a.dClicks || 0)).slice(0, 5);
  const maxViews = topViews.length > 0 ? Math.max(1, Number(topViews[0].dViews || 0)) : 1;
  const maxClicks = topClicks.length > 0 ? Math.max(1, Number(topClicks[0].dClicks || 0)) : 1;
  const totalAccounts = Math.max(1, Number(TOTAL.accounts || ACCOUNTS.length || 1));
  const profilesVisible = (PROFILES || []).filter(
    p => Number(p.accounts || 0) > 0 && String(p.id) !== 'none' && !(typeof HIDDEN_PROFILE_IDS !== 'undefined' && HIDDEN_PROFILE_IDS.has(String(p.id))),
  );
  const maxPlatformAccounts = Math.max(1, ...(PLATFORMS || []).map(p => Number(p.accounts || 0)));
  const platformClicks = (PLATFORMS || []).map(p => {
    const accs = ACCOUNTS.filter(a => a.platform === p.id);
    return {
      id: p.id,
      label: p.label,
      color: p.color,
      clicks: accs.reduce((s, a) => s + Number(a.clicks || 0), 0),
      dClicks: accs.reduce((s, a) => s + Number(a.dClicks || 0), 0)
    };
  }).filter(p => Number(p.clicks || 0) > 0).sort((a, b) => Number(b.clicks || 0) - Number(a.clicks || 0));
  const maxPlatformClicks = platformClicks.length > 0 ? Math.max(1, ...platformClicks.map(p => Number(p.clicks || 0))) : 1;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      height: '100%',
      padding: '0 56px',
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 28,
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 18,
      minHeight: 0,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(TvTopLeaderboardBlock, {
    title: "TOP MOVERS \xB7 24H \xB7 BY VIEW DELTA",
    rows: topViews,
    rankAccent: accent,
    maxDelta: maxViews,
    getTotal: a => a.views,
    getDelta: a => a.dViews,
    getBarMetric: a => a.dViews,
    deltaColor: "#4ade80"
  }), /*#__PURE__*/React.createElement(TvTopLeaderboardBlock, {
    title: "TOP CLICKS \xB7 24H \xB7 BY LINK DELTA",
    rows: topClicks,
    rankAccent: TV_CLICKS_COLOR,
    maxDelta: maxClicks,
    getTotal: a => a.clicks,
    getDelta: a => a.dClicks,
    getBarMetric: a => a.dClicks,
    deltaColor: TV_CLICKS_COLOR
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      minHeight: 0,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 20,
      border: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(255,255,255,0.015)',
      padding: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em',
      marginBottom: 14
    }
  }, "BY PROFILE"), /*#__PURE__*/React.createElement(TvProfileDialsGrid, {
    profiles: profilesVisible,
    totalAccounts: totalAccounts
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 20,
      border: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(255,255,255,0.015)',
      padding: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em',
      marginBottom: 14
    }
  }, "PLATFORM DISTRIBUTION"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, PLATFORMS.map(p => /*#__PURE__*/React.createElement("div", {
    key: p.id,
    style: {
      display: 'grid',
      gridTemplateColumns: '120px 1fr 60px',
      alignItems: 'center',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 2,
      background: p.color
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14
    }
  }, p.label)), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      borderRadius: 2,
      background: 'rgba(255,255,255,0.04)',
      overflow: 'hidden',
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      width: `${Math.min(100, Math.max(0, Number(p.accounts || 0) / maxPlatformAccounts * 100))}%`,
      background: p.color,
      opacity: 0.85
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 14,
      color: 'rgba(255,255,255,0.6)',
      textAlign: 'right'
    }
  }, p.accounts))))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 20,
      border: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(255,255,255,0.015)',
      padding: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      justifyContent: 'space-between',
      gap: 12,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.45)',
      letterSpacing: '0.24em'
    }
  }, "CLICKS BY PLATFORM"), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 9,
      color: 'rgba(255,255,255,0.32)',
      letterSpacing: '0.12em'
    }
  }, "+24\u0427")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, platformClicks.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,0.35)',
      letterSpacing: '0.08em'
    }
  }, "\u041D\u0435\u0442 \u043F\u0435\u0440\u0435\u0445\u043E\u0434\u043E\u0432 \u043F\u043E \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u0430\u043C") : platformClicks.map(p => {
    const parts = _tvClicksStackParts(p.clicks, p.dClicks);
    const barW = parts ? Math.min(100, parts.total / maxPlatformClicks * 100) : 0;
    const basePct = parts && parts.total > 0 ? parts.base / parts.total * 100 : 100;
    const growthPct = parts && parts.total > 0 ? parts.growth / parts.total * 100 : 0;
    const deltaLabel = _deltaLabel(p.dClicks);
    const growthColor = _growthBarColor(p.color, p.id);
    const deltaColor = Number(p.dClicks || 0) < 0 ? '#f87171' : growthColor;
    return /*#__PURE__*/React.createElement("div", {
      key: `clicks-${p.id}`,
      style: {
        display: 'grid',
        gridTemplateColumns: '120px 1fr 72px',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 2,
        background: p.color
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14
      }
    }, p.label)), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 8,
        borderRadius: 2,
        background: 'rgba(255,255,255,0.04)',
        overflow: 'hidden',
        position: 'relative'
      }
    }, parts && /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        left: 0,
        top: 0,
        bottom: 0,
        width: `${barW}%`,
        display: 'flex',
        flexDirection: 'row',
        borderRadius: 2,
        overflow: 'hidden',
        minWidth: parts.growth > 0 && parts.base > 0 ? 4 : 0
      }
    }, parts.base > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        flex: `0 0 ${basePct}%`,
        background: p.color,
        opacity: 0.95,
        minWidth: parts.growth > 0 ? 2 : 0,
        boxSizing: 'border-box',
        borderRight: parts.growth > 0 ? '2px solid rgba(255,255,255,0.92)' : 'none'
      }
    }), parts.growth > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        flex: `0 0 ${growthPct}%`,
        background: growthColor,
        opacity: 1,
        minWidth: 2,
        boxSizing: 'border-box'
      }
    }))), /*#__PURE__*/React.createElement("div", {
      className: "mono tnum",
      style: {
        fontSize: 13,
        color: 'rgba(255,255,255,0.75)',
        textAlign: 'right',
        lineHeight: 1.25
      }
    }, /*#__PURE__*/React.createElement("div", null, fmt(p.clicks)), deltaLabel && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: deltaColor
      }
    }, deltaLabel)));
  })))));
}
function TVPauseIcon({
  size = 10,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    "aria-hidden": "true",
    style: {
      display: 'block',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("rect", {
    x: "6",
    y: "5",
    width: "4.5",
    height: "14",
    rx: "1",
    fill: color
  }), /*#__PURE__*/React.createElement("rect", {
    x: "13.5",
    y: "5",
    width: "4.5",
    height: "14",
    rx: "1",
    fill: color
  }));
}
function TVPlayIcon({
  size = 10,
  color = 'currentColor'
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    "aria-hidden": "true",
    style: {
      display: 'block',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M9 6.5v11L18 12z",
    fill: color
  }));
}

// ── Bottom ticker ──────────────────────────────────────────
function TVTicker({
  accent
}) {
  const items = useMemoTV(() => {
    return ACCOUNTS.filter(a => a.dViews > 0).slice(0, 10).map(a => `${_tvBroadcastAccountTitle(a)} +${fmt(a.dViews)} VIEWS`);
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 28,
      left: 0,
      right: 0,
      display: 'flex',
      alignItems: 'center',
      gap: 20,
      padding: '0 56px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flexShrink: 0,
      padding: '8px 14px',
      borderRadius: 999,
      background: accent,
      color: '#000',
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.18em',
      fontFamily: 'JetBrains Mono, monospace'
    }
  }, "LIVE"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'hidden',
      maskImage: 'linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      display: 'flex',
      gap: 48,
      whiteSpace: 'nowrap',
      animation: 'tickerScroll 80s linear infinite',
      fontSize: 15,
      color: 'rgba(255,255,255,0.7)',
      letterSpacing: '0.06em'
    }
  }, [...items, ...items, ...items].map((it, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      display: 'inline-flex',
      gap: 8,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: accent
    }
  }, "\u25C6"), " ", it)))), /*#__PURE__*/React.createElement("style", null, `
        @keyframes tickerScroll { from { transform: translateX(0); } to { transform: translateX(-33.333%); } }
      `));
}
function TVSceneTransport({
  accent,
  autoPaused,
  setAutoPaused,
  compact
}) {
  const playing = !autoPaused;
  // ~27% меньше прежних 28×28 / 30×30 — компактнее на бродкасте
  const sz = compact ? 20 : 22;
  const iconSz = compact ? 8 : 9;
  const iconColor = accent;
  const btnStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: sz,
    height: sz,
    padding: 0,
    borderRadius: 6,
    flexShrink: 0,
    cursor: 'pointer',
    border: 'none',
    boxShadow: 'none',
    background: `${accent}28`,
    color: iconColor
  };
  const title = playing ? 'Пауза: остановить автоматическое переключение сцен' : 'Плей: снова переключать сцены автоматически';
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    title: title,
    "aria-label": title,
    "aria-pressed": playing ? 'true' : 'false',
    onClick: () => setAutoPaused?.(!autoPaused),
    style: btnStyle
  }, playing ? /*#__PURE__*/React.createElement(TVPauseIcon, {
    size: iconSz,
    color: iconColor
  }) : /*#__PURE__*/React.createElement(TVPlayIcon, {
    size: iconSz,
    color: iconColor
  }));
}
function TVSceneIndicator({
  total,
  current,
  accent,
  onSelect,
  autoPaused = false,
  setAutoPaused
}) {
  const isMobile = useIsMobile(980);
  if (isMobile) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 14,
        zIndex: 30,
        pointerEvents: 'none',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        pointerEvents: 'auto'
      }
    }, /*#__PURE__*/React.createElement(TVSceneTransport, {
      accent: accent,
      autoPaused: autoPaused,
      setAutoPaused: setAutoPaused,
      compact: true
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'center',
        gap: 8,
        pointerEvents: 'auto'
      }
    }, Array.from({
      length: total
    }).map((_, i) => /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      onClick: () => onSelect?.(i),
      title: `Сцена ${i + 1}`,
      style: {
        width: i === current ? 9 : 7,
        height: i === current ? 9 : 7,
        borderRadius: 999,
        background: i === current ? accent : 'rgba(255,255,255,0.35)',
        border: i === current ? `1px solid ${accent}` : '1px solid rgba(255,255,255,0.25)',
        boxShadow: i === current ? `0 0 10px ${accent}66` : 'none',
        transition: 'all 0.2s ease',
        cursor: 'pointer',
        padding: 0
      }
    }))));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 110,
      right: 20,
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      alignItems: 'flex-end',
      zIndex: 20
    }
  }, /*#__PURE__*/React.createElement(TVSceneTransport, {
    accent: accent,
    autoPaused: autoPaused,
    setAutoPaused: setAutoPaused,
    compact: false
  }), Array.from({
    length: total
  }).map((_, i) => /*#__PURE__*/React.createElement("button", {
    key: i,
    type: "button",
    onClick: () => onSelect?.(i),
    title: `Переключить на сцену ${i + 1}`,
    style: {
      width: i === current ? 32 : 12,
      height: 3,
      borderRadius: 2,
      background: i === current ? accent : 'rgba(255,255,255,0.15)',
      transition: 'all 0.25s ease',
      border: 'none',
      cursor: 'pointer',
      padding: 0
    }
  })));
}
Object.assign(window, {
  TVScreen
});

// ===== screen-accounts.jsx =====
// Accounts list screen — atomic-themed redesign of the table view.

const {
  useState: useStateAcc,
  useMemo: useMemoAcc
} = React;
function AccountsScreen({
  tweaks,
  onNavigate,
  onDataChanged,
  onOpenAccount,
  onOpenGlobalModal
}) {
  const [deltaPeriodSaving, setDeltaPeriodSaving] = React.useState(false);
  const [deltaUiEpoch, bumpDeltaUi] = React.useReducer(x => x + 1, 0);
  const accent = tweaks.accent || '#6aa9ff';
  const view = tweaks.accounts_view || 'table'; // table | cards
  const isMobile = useIsMobile(980);
  const [platform, setPlatform] = useStateAcc(() => window.localStorage.getItem('nf_platform') || 'all');
  const [profile, setProfile] = useStateAcc(() => window.localStorage.getItem('nf_profile') || 'all');
  const [status, setStatus] = useStateAcc(() => window.localStorage.getItem('nf_status') || 'all');
  const [search, setSearch] = useStateAcc(() => window.localStorage.getItem('nf_search') || '');
  const [profileSearch, setProfileSearch] = useStateAcc('');
  const [showHidden, setShowHidden] = useStateAcc(() => window.localStorage.getItem('nf_show_hidden') === '1');
  const [sortKey, setSortKey] = useStateAcc('views');
  const [sortOrder, setSortOrder] = useStateAcc('desc');
  const [sortByDelta, setSortByDelta] = useStateAcc(() => window.localStorage.getItem('nf_sort_by_delta') === '1');
  const [hiddenPlatforms, setHiddenPlatforms] = useStateAcc(new Set());
  const [hiddenProfileIds, setHiddenProfileIds] = useStateAcc(new Set());
  const [tab, setTab] = useStateAcc('accounts');
  const [busy, setBusy] = useStateAcc(false);
  const [rowBusyId, setRowBusyId] = useStateAcc(null);
  const [profileEditor, setProfileEditor] = useStateAcc(null); // { mode, id?, name, color }
  const [profileEditorBusy, setProfileEditorBusy] = useStateAcc(false);
  React.useEffect(() => {
    window.localStorage.setItem('nf_platform', platform);
  }, [platform]);
  React.useEffect(() => {
    window.localStorage.setItem('nf_profile', profile);
  }, [profile]);
  React.useEffect(() => {
    window.localStorage.setItem('nf_status', status);
  }, [status]);
  React.useEffect(() => {
    window.localStorage.setItem('nf_search', search);
  }, [search]);
  React.useEffect(() => {
    window.localStorage.setItem('nf_show_hidden', showHidden ? '1' : '0');
  }, [showHidden]);
  React.useEffect(() => {
    window.localStorage.setItem('nf_sort_by_delta', sortByDelta ? '1' : '0');
  }, [sortByDelta]);
  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const v = await _fetchJson('/api/accounts/visibility/');
        if (!mounted) return;
        setHiddenPlatforms(new Set((v?.hidden_platforms || []).map(String)));
        setHiddenProfileIds(new Set((v?.hidden_profile_ids || []).map(x => String(x))));
      } catch {
        // ignore
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);
  const setTabAndNavigate = nextTab => {
    setTab(nextTab);
    if (nextTab === 'analytics') onNavigate?.('analytics');
  };
  const resetFilters = () => {
    setPlatform('all');
    setProfile('all');
    setStatus('all');
    setSearch('');
    setProfileSearch('');
    setShowHidden(false);
    setSortKey('views');
    setSortOrder('desc');
    setSortByDelta(false);
  };
  const cycleAccountDeltaPeriod = async () => {
    if (deltaPeriodSaving) return;
    const next = _nextDeltaPeriodDays(ACCOUNT_DELTA_PERIOD_DAYS);
    const cached = DELTA_PERIOD_CACHE[next];
    if (cached) {
      const snap = {
        accounts: cached.accounts.map(x => ({
          ...x
        })),
        total: JSON.parse(JSON.stringify(cached.total)),
        platforms: cached.platforms.map(x => ({
          ...x
        }))
      };
      if (_applyDeltaSnapshotToGlobals(snap)) {
        ACCOUNT_DELTA_PERIOD_DAYS = next;
        bumpDeltaUi();
      }
      void _postJson('/api/accounts/schedule/', {
        account_delta_period_days: next
      }).catch(() => {});
      _scheduleDeltaPrefetchExcept(next);
      return;
    }
    setDeltaPeriodSaving(true);
    try {
      const [sr, ar] = await Promise.all([_fetchJsonSoft(`/api/accounts/summary/?include_hidden=1&delta_period_days=${next}`), _fetchJsonSoft(`/api/accounts/?include_hidden=1&delta_period_days=${next}`)]);
      if (sr.ok && ar.ok && Array.isArray(ar.data) && sr.data) {
        const snap = _buildDeltaSnapshot(sr.data, ar.data);
        if (snap && _applyDeltaSnapshotToGlobals(snap)) {
          ACCOUNT_DELTA_PERIOD_DAYS = next;
          _storeDeltaCacheForPeriod(next, snap);
          bumpDeltaUi();
        }
      } else {
        await _postJson('/api/accounts/schedule/', {
          account_delta_period_days: next
        });
        await onDataChanged?.();
        return;
      }
      void _postJson('/api/accounts/schedule/', {
        account_delta_period_days: next
      }).catch(() => {});
      _scheduleDeltaPrefetchExcept(next);
    } catch (e) {
      await uiAlert(`Не удалось переключить период: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setDeltaPeriodSaving(false);
    }
  };
  const saveVisibility = async (nextPlatforms, nextProfileIds) => {
    await _postJson('/api/accounts/visibility/', {
      hidden_platforms: Array.from(nextPlatforms),
      hidden_profile_ids: Array.from(nextProfileIds).map(x => Number(x))
    });
    setHiddenPlatforms(new Set(nextPlatforms));
    setHiddenProfileIds(new Set(nextProfileIds));
    await onDataChanged?.();
  };
  const togglePlatformHidden = async platformId => {
    const nextPlatforms = new Set(hiddenPlatforms);
    if (nextPlatforms.has(platformId)) nextPlatforms.delete(platformId);else nextPlatforms.add(platformId);
    await saveVisibility(nextPlatforms, hiddenProfileIds);
  };
  const toggleProfileHidden = async profileId => {
    const nextProfiles = new Set(hiddenProfileIds);
    if (nextProfiles.has(profileId)) nextProfiles.delete(profileId);else nextProfiles.add(profileId);
    await saveVisibility(hiddenPlatforms, nextProfiles);
  };
  const createProfile = async ({
    name,
    color
  }) => {
    const profileName = String(name || '').trim();
    if (!profileName) return;
    try {
      await _postJson('/api/accounts/profiles/', {
        name: profileName,
        color: color || '#6366f1'
      });
      await onDataChanged?.();
      setProfileSearch('');
      await uiAlert(`Профиль "${profileName}" добавлен.`, 'Профили');
    } catch (e) {
      await uiAlert(`Не удалось добавить профиль: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    }
  };
  const saveProfileEditor = async ({
    name,
    color
  }) => {
    const profileName = String(name || '').trim();
    if (!profileName) return;
    setProfileEditorBusy(true);
    try {
      if (profileEditor?.mode === 'edit' && profileEditor?.id != null) {
        await _patchJson(`/api/accounts/profiles/${profileEditor.id}/`, {
          name: profileName,
          color: color || '#6366f1'
        });
      } else {
        await createProfile({
          name: profileName,
          color
        });
      }
      setProfileEditor(null);
    } finally {
      setProfileEditorBusy(false);
    }
  };
  const deleteProfile = async profileToDelete => {
    if (!profileToDelete?.id) return;
    const confirmed = await uiConfirm(`Удалить профиль "${profileToDelete.label}"?`, 'Подтвердите удаление профиля');
    if (!confirmed) return;
    try {
      await _delete(`/api/accounts/profiles/${profileToDelete.id}/`);
      await onDataChanged?.();
      if (profile === profileToDelete.id) setProfile('all');
      await uiAlert(`Профиль "${profileToDelete.label}" удален.`, 'Профили');
    } catch (e) {
      await uiAlert(`Не удалось удалить профиль: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    }
  };
  const handleRefreshAll = async () => {
    setBusy(true);
    try {
      await _postJson('/api/accounts/refresh_all/', {});
      await onDataChanged?.();
    } catch (e) {
      await uiAlert(`Не удалось обновить: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setBusy(false);
    }
  };
  const {
    filtered,
    barStats
  } = useMemoAcc(() => {
    const rows = ACCOUNTS.filter(a => (showHidden || !a.isPlatformHidden && !a.isProfileHidden) && (platform === 'all' || a.platform === platform) && (profile === 'all' || a.profile === profile) && (status === 'all' || (status === 'avail' ? !a.unavailable : a.unavailable)) && (!search.trim() || a.name.toLowerCase().includes(search.toLowerCase()) || a.handle.toLowerCase().includes(search.toLowerCase())));
    const barStats = _aggregateBarStatsFromAccountRows(rows);
    const getter = a => {
      if (sortByDelta) {
        if (sortKey === 'followers') return _toSortableNumber(a.dFollowers);
        if (sortKey === 'likes') return _toSortableNumber(a.dLikes);
        if (sortKey === 'posts') return _toSortableNumber(a.dPosts);
        if (sortKey === 'clicks') return _toSortableNumber(a.dClicks);
        return _toSortableNumber(a.dViews);
      }
      if (sortKey === 'followers') return _toSortableNumber(a.followers);
      if (sortKey === 'likes') return _toSortableNumber(a.likes);
      if (sortKey === 'posts') return _toSortableNumber(a.posts);
      if (sortKey === 'clicks') return _toSortableNumber(a.clicks);
      return _toSortableNumber(a.views);
    };
    rows.sort((a, b) => {
      const diff = getter(a) - getter(b);
      return sortOrder === 'asc' ? diff : -diff;
    });
    return {
      filtered: rows,
      barStats
    };
  }, [platform, profile, status, search, showHidden, sortKey, sortOrder, sortByDelta, deltaUiEpoch]);
  const platformFilterOptions = useMemoAcc(() => {
    const fromAll = (ALL_PLATFORMS || []).map(p => ({
      id: p.id,
      label: p.label,
      color: p.color,
      hidden: hiddenPlatforms.has(String(p.id))
    }));
    if (fromAll.length > 0) {
      return showHidden ? fromAll : fromAll.filter(p => !p.hidden);
    }
    const fallback = (PLATFORMS || []).map(p => ({
      id: p.id,
      label: p.label,
      color: p.color,
      hidden: hiddenPlatforms.has(String(p.id))
    }));
    return showHidden ? fallback : fallback.filter(p => !p.hidden);
  }, [showHidden, hiddenPlatforms]);
  const handleMetricSort = key => {
    if (sortKey === key) {
      setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    style: _pageShellStyle(),
    "data-screen-label": "Accounts List"
  }, /*#__PURE__*/React.createElement(TopBar, {
    accent: accent,
    barStats: barStats,
    onRefreshAll: () => onOpenGlobalModal?.('refresh_all'),
    onOpenSchedule: () => onOpenGlobalModal?.('schedule'),
    onOpenAddList: () => onOpenGlobalModal?.('add_list'),
    onOpenAddOne: () => onOpenGlobalModal?.('add_one'),
    busy: busy,
    deltaPeriodDays: ACCOUNT_DELTA_PERIOD_DAYS,
    onDeltaPeriodCycle: cycleAccountDeltaPeriod,
    deltaPeriodBusy: deltaPeriodSaving
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '280px 1fr',
      gap: 0
    }
  }, /*#__PURE__*/React.createElement(Sidebar, {
    profile: profile,
    setProfile: setProfile,
    tab: tab,
    setTab: setTabAndNavigate,
    accent: accent,
    profileSearch: profileSearch,
    setProfileSearch: setProfileSearch,
    hiddenProfileIds: hiddenProfileIds,
    onToggleProfileHidden: toggleProfileHidden,
    showHidden: showHidden,
    onCreateProfile: () => setProfileEditor({
      mode: 'create',
      name: '',
      color: '#6366f1'
    }),
    onEditProfile: profileToEdit => setProfileEditor({
      mode: 'edit',
      id: profileToEdit.id,
      name: profileToEdit.label || '',
      color: profileToEdit.color || '#6366f1'
    }),
    onDeleteProfile: deleteProfile,
    stackOrder: isMobile ? 2 : 0
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      padding: _isEmbedMode() ? isMobile ? '14px 12px 64px' : '20px 20px 64px' : isMobile ? '14px 12px 104px' : '28px 36px 60px',
      minWidth: 0,
      order: isMobile ? 1 : 0,
      flex: _isEmbedMode() ? 1 : undefined,
      minHeight: _isEmbedMode() ? 0 : undefined,
      overflow: _isEmbedMode() ? 'auto' : undefined
    }
  }, /*#__PURE__*/React.createElement(FilterBar, {
    platform: platform,
    setPlatform: setPlatform,
    status: status,
    setStatus: setStatus,
    accent: accent,
    search: search,
    setSearch: setSearch,
    onReset: resetFilters,
    showHidden: showHidden,
    setShowHidden: setShowHidden,
    hiddenPlatforms: hiddenPlatforms,
    onTogglePlatformHidden: togglePlatformHidden,
    platformOptions: platformFilterOptions,
    sortKey: sortKey,
    sortOrder: sortOrder,
    onMetricSort: isMobile ? handleMetricSort : undefined,
    sortByDelta: sortByDelta,
    onToggleSortByDelta: () => setSortByDelta(v => !v)
  }), LOAD_STATE.hasError && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14,
      padding: '10px 12px',
      borderRadius: 10,
      border: '1px solid #ef444455',
      background: '#ef444415',
      color: '#fca5a5',
      fontSize: 13
    }
  }, LOAD_STATE.errorMessage), filtered.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 28,
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E \u043F\u043E \u0442\u0435\u043A\u0443\u0449\u0438\u043C \u0444\u0438\u043B\u044C\u0442\u0440\u0430\u043C.") : (isMobile ? 'cards' : view) === 'table' ? /*#__PURE__*/React.createElement(AccountsTable, {
    rows: filtered,
    accent: accent,
    sortKey: sortKey,
    sortOrder: sortOrder,
    setSortKey: setSortKey,
    setSortOrder: setSortOrder,
    sortByDelta: sortByDelta,
    setSortByDelta: setSortByDelta,
    onOpenAccount: onOpenAccount,
    onRefreshOne: async id => {
      setRowBusyId(id);
      try {
        await _postJson(`/api/accounts/${id}/refresh/`, {});
        await onDataChanged?.();
      } catch (e) {
        await uiAlert(`Не удалось обновить аккаунт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      } finally {
        setRowBusyId(null);
      }
    },
    onDeleteOne: async id => {
      if (!(await uiConfirm('Удалить аккаунт?', 'Подтвердите удаление'))) return;
      setRowBusyId(id);
      try {
        await _delete(`/api/accounts/${id}/`);
        await onDataChanged?.();
      } catch (e) {
        await uiAlert(`Не удалось удалить аккаунт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      } finally {
        setRowBusyId(null);
      }
    },
    rowBusyId: rowBusyId
  }) : /*#__PURE__*/React.createElement(AccountsCards, {
    rows: filtered,
    accent: accent,
    onOpenAccount: onOpenAccount,
    onRefreshOne: async id => {
      setRowBusyId(id);
      try {
        await _postJson(`/api/accounts/${id}/refresh/`, {});
        await onDataChanged?.();
      } catch (e) {
        await uiAlert(`Не удалось обновить аккаунт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      } finally {
        setRowBusyId(null);
      }
    },
    onDeleteOne: async id => {
      if (!(await uiConfirm('Удалить аккаунт?', 'Подтвердите удаление'))) return;
      setRowBusyId(id);
      try {
        await _delete(`/api/accounts/${id}/`);
        await onDataChanged?.();
      } catch (e) {
        await uiAlert(`Не удалось удалить аккаунт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      } finally {
        setRowBusyId(null);
      }
    },
    rowBusyId: rowBusyId
  }))), profileEditor && /*#__PURE__*/React.createElement(ProfileEditorModal, {
    accent: accent,
    mode: profileEditor.mode,
    initialName: profileEditor.name,
    initialColor: profileEditor.color,
    busy: profileEditorBusy,
    onSubmit: saveProfileEditor,
    onClose: () => {
      if (!profileEditorBusy) setProfileEditor(null);
    }
  }));
}
function _topBarStatsFromTotal() {
  return {
    followers: {
      value: TOTAL.followers.value,
      delta: TOTAL.followers.delta
    },
    views: {
      value: TOTAL.views.value,
      delta: TOTAL.views.delta
    },
    likes: {
      value: TOTAL.likes.value,
      delta: TOTAL.likes.delta
    },
    posts: {
      value: TOTAL.posts.value,
      delta: TOTAL.posts.delta
    },
    clicks: {
      value: TOTAL.clicks.value,
      delta: TOTAL.clicks.delta
    }
  };
}

/** Суммы по списку аккаунтов (как на старом фронте) — для шапки при активных фильтрах. */
function _aggregateBarStatsFromAccountRows(rows) {
  const z = {
    value: 0,
    delta: 0
  };
  const out = {
    followers: {
      ...z
    },
    views: {
      ...z
    },
    likes: {
      ...z
    },
    posts: {
      ...z
    },
    clicks: {
      ...z
    },
    count: 0
  };
  if (!Array.isArray(rows) || rows.length === 0) return out;
  out.count = rows.length;
  for (const a of rows) {
    out.followers.value += Number(a.followers || 0);
    out.views.value += Number(a.views || 0);
    out.likes.value += Number(a.likes || 0);
    out.posts.value += Number(a.posts || 0);
    out.clicks.value += Number(a.clicks || 0);
    out.followers.delta += Number(a.dFollowers ?? 0);
    out.views.delta += Number(a.dViews ?? 0);
    out.likes.delta += Number(a.dLikes ?? 0);
    out.posts.delta += Number(a.dPosts ?? 0);
    out.clicks.delta += Number(a.dClicks ?? 0);
  }
  return out;
}
function DeltaPeriodCycleButton({
  value,
  onCycle,
  disabled,
  isMobile,
  accent = '#6aa9ff'
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: !!disabled,
    onClick: onCycle,
    className: "mono tnum",
    title: "\u041F\u0435\u0440\u0438\u043E\u0434 \u043F\u0440\u0438\u0440\u043E\u0441\u0442\u043E\u0432: \u043D\u0430\u0436\u043C\u0438\u0442\u0435, \u0447\u0442\u043E\u0431\u044B \u043F\u0435\u0440\u0435\u043A\u043B\u044E\u0447\u0438\u0442\u044C 1\u0434 \u2192 7\u0434 \u2192 30\u0434",
    style: {
      minWidth: isMobile ? 52 : 48,
      padding: isMobile ? '8px 12px' : '8px 12px',
      borderRadius: 10,
      border: `1px solid ${accent}88`,
      background: 'rgba(106,169,255,0.12)',
      color: 'var(--ink)',
      fontSize: isMobile ? 12 : 12,
      fontWeight: 700,
      letterSpacing: '0.04em',
      cursor: disabled ? 'wait' : 'pointer',
      fontFamily: 'inherit',
      flexShrink: 0,
      opacity: disabled ? 0.65 : 1
    }
  }, value, "\u0434");
}
function TopBar({
  accent,
  barStats,
  onRefreshAll,
  onOpenSchedule,
  onOpenAddList,
  onOpenAddOne,
  busy,
  deltaPeriodDays,
  onDeltaPeriodCycle,
  deltaPeriodBusy
}) {
  const isMobile = useIsMobile(980);
  const showDelta = typeof onDeltaPeriodCycle === 'function';
  const s = barStats || _topBarStatsFromTotal();
  const stats = [{
    label: isMobile ? 'ПОДП' : 'ПОДПИСЧИКИ',
    value: s.followers.value,
    delta: s.followers.delta,
    color: '#4ade80'
  }, {
    label: isMobile ? 'ПРОСМ' : 'ПРОСМОТРЫ',
    value: s.views.value,
    delta: s.views.delta,
    color: '#ec4899'
  }, {
    label: isMobile ? 'ЛАЙК' : 'ЛАЙКИ',
    value: s.likes.value,
    delta: s.likes.delta,
    color: '#f59e0b'
  }, {
    label: isMobile ? 'ПУБЛ' : 'ПУБЛИКАЦИИ',
    value: s.posts.value,
    delta: s.posts.delta,
    color: accent
  }, {
    label: isMobile ? 'ПЕР' : 'ПЕРЕХОДЫ',
    value: s.clicks.value,
    delta: s.clicks.delta,
    color: '#a78bfa'
  }];
  return /*#__PURE__*/React.createElement("header", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 50,
      padding: '18px 36px',
      background: 'rgba(5,6,8,0.85)',
      backdropFilter: 'blur(14px)',
      borderBottom: '1px solid var(--line)',
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '260px 1fr auto',
      gap: isMobile ? 12 : 32,
      alignItems: 'center',
      padding: isMobile ? '12px 12px' : '18px 36px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      fontWeight: 600,
      letterSpacing: '-0.01em'
    }
  }, "AccountsStats"), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      textTransform: 'uppercase'
    }
  }, "v2.0 \xB7 ATOMIC"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: isMobile ? 'grid' : 'flex',
      gridTemplateColumns: isMobile ? 'repeat(2, minmax(0, 1fr))' : 'repeat(5, minmax(0, 1fr))',
      alignItems: 'center',
      gap: isMobile ? 8 : 8,
      overflow: 'visible'
    }
  }, stats.map((s, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: s.label
  }, !isMobile && i > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      width: 1,
      height: 36,
      background: 'var(--line)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      padding: isMobile ? '0 2px' : '0 14px',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: isMobile ? 8 : 10,
      color: 'var(--ink-mute)',
      letterSpacing: isMobile ? '0.12em' : '0.18em'
    }
  }, s.label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: isMobile ? 4 : 8,
      marginTop: 2,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "tnum",
    style: {
      fontSize: isMobile ? 22 : 22,
      fontWeight: 600,
      letterSpacing: '-0.01em',
      lineHeight: 0.95,
      minWidth: 0,
      whiteSpace: 'nowrap'
    }
  }, fmt(s.value)), _hasDelta(s.delta) && /*#__PURE__*/React.createElement("span", {
    className: "mono tnum",
    style: {
      fontSize: isMobile ? 11 : 12,
      color: s.color,
      whiteSpace: 'nowrap'
    }
  }, Number(s.delta) >= 0 ? '+' : '', fmt(s.delta))))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: isMobile ? 'column' : 'row',
      alignItems: isMobile ? 'stretch' : 'flex-start',
      gap: isMobile ? 8 : 10,
      width: '100%',
      justifyContent: 'flex-end',
      minWidth: 0
    }
  }, showDelta && /*#__PURE__*/React.createElement(DeltaPeriodCycleButton, {
    value: deltaPeriodDays ?? 1,
    onCycle: onDeltaPeriodCycle,
    disabled: deltaPeriodBusy,
    isMobile: isMobile,
    accent: accent
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? 'repeat(4, minmax(0, 1fr))' : 'repeat(4, auto)',
      gap: 10,
      width: isMobile ? '100%' : undefined,
      flex: isMobile ? undefined : '0 1 auto',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(Btn, {
    onClick: onRefreshAll,
    style: isMobile ? {
      width: '100%',
      justifyContent: 'center'
    } : undefined
  }, isMobile ? '↻' : busy ? 'Обновление...' : '↻ Обновить всё'), /*#__PURE__*/React.createElement(Btn, {
    accent: accent,
    onClick: onOpenSchedule,
    style: isMobile ? {
      width: '100%',
      justifyContent: 'center'
    } : undefined
  }, isMobile ? '⏱' : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: '#4ade80',
      display: 'inline-block',
      marginRight: 6,
      boxShadow: '0 0 8px #4ade80'
    }
  }), "\u0410\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0435")), /*#__PURE__*/React.createElement(Btn, {
    onClick: onOpenAddList,
    style: isMobile ? {
      width: '100%',
      justifyContent: 'center'
    } : undefined
  }, isMobile ? '≡' : '+ Список'), /*#__PURE__*/React.createElement(Btn, {
    onClick: onOpenAddOne,
    style: isMobile ? {
      width: '100%',
      justifyContent: 'center'
    } : undefined
  }, isMobile ? '+' : '+ Добавить'))));
}
function AtomLogoMini({
  size = 32,
  accent
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 100 100",
    width: size,
    height: size
  }, /*#__PURE__*/React.createElement("ellipse", {
    cx: "50",
    cy: "50",
    rx: "40",
    ry: "14",
    fill: "none",
    stroke: accent,
    strokeWidth: "2",
    opacity: "0.7"
  }), /*#__PURE__*/React.createElement("ellipse", {
    cx: "50",
    cy: "50",
    rx: "40",
    ry: "14",
    fill: "none",
    stroke: accent,
    strokeWidth: "2",
    opacity: "0.7",
    transform: "rotate(60 50 50)"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "50",
    cy: "50",
    r: "8",
    fill: accent
  }));
}
function Btn({
  children,
  primary,
  accent = '#6aa9ff',
  onClick,
  style
}) {
  const isMobile = useIsMobile(980);
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      minHeight: isMobile ? 42 : undefined,
      padding: isMobile ? '10px 12px' : '10px 16px',
      borderRadius: 12,
      background: primary ? accent : 'rgba(255,255,255,0.04)',
      color: primary ? '#000' : 'var(--ink)',
      border: primary ? 'none' : '1px solid var(--line)',
      fontSize: isMobile ? 12 : 13,
      fontWeight: primary ? 600 : 500,
      cursor: 'pointer',
      display: 'inline-flex',
      alignItems: 'center',
      transition: 'all .15s',
      ...style
    }
  }, children);
}
function Sidebar({
  profile,
  setProfile,
  tab,
  setTab,
  accent,
  profileSearch,
  setProfileSearch,
  hiddenProfileIds,
  onToggleProfileHidden,
  showHidden,
  onCreateProfile,
  onEditProfile,
  onDeleteProfile,
  stackOrder = 0
}) {
  const isMobile = useIsMobile(980);
  const matchedProfiles = PROFILES.filter(p => {
    const matches = p.id === 'none' || p.label.toLowerCase().includes(profileSearch.toLowerCase());
    if (!matches) return false;
    return true;
  });
  const visibleProfiles = matchedProfiles.filter(p => {
    if (p.id === 'none') return true;
    return !hiddenProfileIds?.has(String(p.id));
  });
  const hiddenProfiles = matchedProfiles.filter(p => p.id !== 'none' && hiddenProfileIds?.has(String(p.id)));
  const totalProfileAccounts = PROFILES.reduce((sum, p) => sum + Number(p.accounts || 0), 0);
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      order: stackOrder,
      borderRight: isMobile ? 'none' : '1px solid var(--line)',
      borderBottom: isMobile ? '1px solid var(--line)' : 'none',
      padding: isMobile ? '12px' : '24px 20px',
      position: isMobile ? 'static' : 'sticky',
      top: isMobile ? 'auto' : 80,
      height: isMobile ? 'auto' : 'calc(100vh - 80px)',
      maxHeight: isMobile ? 'none' : 'calc(100vh - 80px)',
      overflowY: isMobile ? 'visible' : 'auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4,
      padding: 4,
      background: 'rgba(255,255,255,0.025)',
      borderRadius: 12,
      border: '1px solid var(--line)'
    }
  }, [{
    id: 'accounts',
    label: 'Аккаунты'
  }, {
    id: 'analytics',
    label: 'Аналитика'
  }].map(t => /*#__PURE__*/React.createElement("button", {
    key: t.id,
    onClick: () => setTab(t.id),
    style: {
      flex: 1,
      padding: '8px 12px',
      borderRadius: 9,
      border: 'none',
      cursor: 'pointer',
      background: tab === t.id ? '#fff' : 'transparent',
      color: tab === t.id ? '#000' : 'var(--ink-dim)',
      fontSize: 13,
      fontWeight: tab === t.id ? 600 : 500
    }
  }, t.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 24
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr auto',
      gap: 8,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: profileSearch,
    onChange: e => setProfileSearch(e.target.value),
    placeholder: "\u041F\u043E\u0438\u0441\u043A \u043F\u0440\u043E\u0444\u0438\u043B\u0435\u0439",
    style: {
      width: '100%',
      padding: '10px 14px 10px 34px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)',
      color: 'var(--ink)',
      fontSize: 13,
      fontFamily: 'inherit'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: 12,
      top: '50%',
      transform: 'translateY(-50%)',
      color: 'var(--ink-mute)',
      fontSize: 12
    }
  }, "\u2315")), /*#__PURE__*/React.createElement("button", {
    onClick: () => onCreateProfile?.(),
    title: "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043F\u0440\u043E\u0444\u0438\u043B\u044C",
    style: {
      width: 34,
      height: 34,
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.06)',
      color: '#fff',
      cursor: 'pointer',
      fontSize: 20,
      lineHeight: '30px',
      padding: 0
    }
  }, "+")), /*#__PURE__*/React.createElement(SidebarItem, {
    active: profile === 'all',
    onClick: () => setProfile('all'),
    label: "\u0412\u0441\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u0438",
    count: totalProfileAccounts,
    dot: "ring",
    accent: accent
  }), /*#__PURE__*/React.createElement(SidebarItem, {
    active: profile === 'none',
    onClick: () => setProfile('none'),
    label: "\u0411\u0435\u0437 \u043F\u0440\u043E\u0444\u0438\u043B\u044F",
    count: PROFILE_META.none?.accounts || 0,
    dim: true
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: 'var(--line)',
      margin: '14px 0'
    }
  }), visibleProfiles.filter(p => p.id !== 'none').map(p => /*#__PURE__*/React.createElement(SidebarItem, {
    key: p.id,
    active: profile === p.id,
    onClick: () => setProfile(p.id),
    label: p.label,
    count: p.accounts,
    color: p.color,
    hidden: hiddenProfileIds?.has(String(p.id)),
    onToggleHidden: () => onToggleProfileHidden?.(String(p.id)),
    onEdit: () => onEditProfile?.(p),
    onDelete: () => onDeleteProfile?.(p)
  })), hiddenProfiles.length > 0 && showHidden && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: 'var(--line)',
      margin: '14px 0'
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: '#86efac',
      letterSpacing: '0.16em',
      marginBottom: 8
    }
  }, "\u0421\u041A\u0420\u042B\u0422\u042B\u0415 \u041F\u0420\u041E\u0424\u0418\u041B\u0418"), hiddenProfiles.map(p => /*#__PURE__*/React.createElement(SidebarItem, {
    key: `hidden-${p.id}`,
    active: profile === p.id,
    onClick: () => setProfile(p.id),
    label: p.label,
    count: p.accounts,
    color: p.color,
    hidden: true,
    onToggleHidden: () => onToggleProfileHidden?.(String(p.id)),
    onEdit: () => onEditProfile?.(p),
    onDelete: () => onDeleteProfile?.(p)
  })))));
}
function SidebarItem({
  active,
  onClick,
  label,
  count,
  color,
  dot,
  dim,
  accent,
  hidden,
  onToggleHidden,
  onEdit,
  onDelete
}) {
  const isMobile = useIsMobile(980);
  const hasActions = !!(onToggleHidden || onEdit || onDelete);
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [hovered, setHovered] = React.useState(false);
  const menuRef = React.useRef(null);
  const showMoreButton = isMobile || hovered || menuOpen;
  React.useEffect(() => {
    if (!menuOpen) return undefined;
    const onDocMouseDown = e => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [menuOpen]);
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
    style: {
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
      padding: '10px 12px',
      borderRadius: 10,
      cursor: 'pointer',
      background: active ? 'rgba(255,255,255,0.04)' : 'transparent',
      border: `1px solid ${active ? 'var(--line-2)' : 'transparent'}`,
      marginBottom: 2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, color ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 22,
      height: 22,
      borderRadius: 999,
      background: `${color}26`,
      color,
      fontSize: 11,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontWeight: 700
    }
  }, label.charAt(0)) : /*#__PURE__*/React.createElement("span", {
    style: {
      width: 22,
      height: 22,
      borderRadius: 999,
      border: `1.5px solid ${active ? 'var(--ink-dim)' : 'var(--line-2)'}`,
      opacity: dim ? 0.4 : 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      color: dim ? 'var(--ink-mute)' : 'var(--ink)'
    }
  }, label)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginLeft: 'auto'
    }
  }, hasActions && /*#__PURE__*/React.createElement("div", {
    ref: menuRef,
    style: {
      position: 'relative',
      display: 'inline-flex',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      setMenuOpen(v => !v);
    },
    title: "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044F \u0441 \u043F\u0440\u043E\u0444\u0438\u043B\u0435\u043C",
    style: {
      width: 22,
      height: 22,
      borderRadius: 7,
      border: '1px solid var(--line)',
      background: menuOpen ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.03)',
      color: '#cbd5e1',
      cursor: 'pointer',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 0,
      fontSize: 14,
      lineHeight: 1,
      opacity: showMoreButton ? 1 : 0,
      pointerEvents: showMoreButton ? 'auto' : 'none',
      transition: 'opacity .14s ease'
    }
  }, "\u22EF"), menuOpen && /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: 'absolute',
      top: 'calc(100% + 6px)',
      right: 0,
      minWidth: 152,
      borderRadius: 10,
      border: '1px solid var(--line-2)',
      background: 'rgba(18,20,28,0.96)',
      backdropFilter: 'blur(10px)',
      boxShadow: '0 10px 28px rgba(0,0,0,0.45)',
      padding: 6,
      zIndex: 30
    }
  }, onEdit && /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      setMenuOpen(false);
      onEdit?.();
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      color: 'var(--ink)',
      cursor: 'pointer',
      textAlign: 'left',
      fontSize: 12,
      padding: '8px 10px',
      borderRadius: 8,
      fontFamily: 'inherit'
    }
  }, "\u270E \u0420\u0435\u0434\u0430\u043A\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C"), onToggleHidden && /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      setMenuOpen(false);
      onToggleHidden?.();
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      color: hidden ? '#86efac' : 'var(--ink)',
      cursor: 'pointer',
      textAlign: 'left',
      fontSize: 12,
      padding: '8px 10px',
      borderRadius: 8,
      fontFamily: 'inherit'
    }
  }, hidden ? '◉ Показать профиль' : '◉ Скрыть профиль'), onDelete && /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      setMenuOpen(false);
      onDelete?.();
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      color: '#fca5a5',
      cursor: 'pointer',
      textAlign: 'left',
      fontSize: 12,
      padding: '8px 10px',
      borderRadius: 8,
      fontFamily: 'inherit'
    }
  }, "\u2715 \u0423\u0434\u0430\u043B\u0438\u0442\u044C"))), /*#__PURE__*/React.createElement("span", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      minWidth: 20,
      textAlign: 'right',
      lineHeight: '18px'
    }
  }, count)));
}
function FilterBar({
  platform,
  setPlatform,
  status,
  setStatus,
  accent,
  search,
  setSearch,
  onReset,
  showHidden,
  setShowHidden,
  hiddenPlatforms,
  onTogglePlatformHidden,
  platformOptions,
  sortKey,
  sortOrder,
  onMetricSort,
  sortByDelta,
  onToggleSortByDelta
}) {
  const isMobile = useIsMobile(980);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: search,
    onChange: e => setSearch(e.target.value),
    placeholder: "\u041F\u043E\u0438\u0441\u043A \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432\u2026",
    style: {
      width: '100%',
      padding: '12px 16px 12px 40px',
      borderRadius: 12,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)',
      color: 'var(--ink)',
      fontSize: 14,
      fontFamily: 'inherit'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: 14,
      top: '50%',
      transform: 'translateY(-50%)',
      color: 'var(--ink-mute)'
    }
  }, "\u2315")), /*#__PURE__*/React.createElement(Pill, {
    active: platform === 'all',
    onClick: () => setPlatform('all')
  }, isMobile ? 'Все' : 'Все'), /*#__PURE__*/React.createElement("button", {
    onClick: () => setShowHidden(!showHidden),
    title: showHidden ? 'Скрыть скрытые аккаунты/платформы/профили' : 'Показать скрытые аккаунты/платформы/профили',
    style: {
      width: 30,
      height: 30,
      borderRadius: 999,
      border: '1px solid ' + (showHidden ? 'rgba(34,197,94,0.5)' : 'var(--line)'),
      background: showHidden ? 'rgba(34,197,94,0.16)' : 'rgba(255,255,255,0.03)',
      color: showHidden ? '#86efac' : '#9ca3af',
      cursor: 'pointer',
      fontSize: 13,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 0
    }
  }, /*#__PURE__*/React.createElement(EyeIcon, {
    size: 13,
    color: showHidden ? '#86efac' : '#9ca3af'
  })), (platformOptions || []).map(p => /*#__PURE__*/React.createElement("div", {
    key: p.id,
    style: {
      position: 'relative',
      display: 'inline-flex',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: platform === p.id,
    onClick: () => setPlatform(p.id),
    dot: isMobile ? undefined : p.color
  }, isMobile ? /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: p.id,
    size: 14
  }) : p.label), /*#__PURE__*/React.createElement("button", {
    onClick: () => onTogglePlatformHidden?.(p.id),
    title: hiddenPlatforms?.has(p.id) ? 'Показать платформу' : 'Скрыть платформу',
    style: {
      position: 'absolute',
      top: -6,
      right: -6,
      width: 18,
      height: 18,
      borderRadius: 999,
      border: `1px solid ${hiddenPlatforms?.has(p.id) ? 'rgba(34,197,94,0.45)' : 'var(--line)'}`,
      background: hiddenPlatforms?.has(p.id) ? 'rgba(34,197,94,0.16)' : 'rgba(255,255,255,0.03)',
      color: hiddenPlatforms?.has(p.id) ? '#86efac' : '#cbd5e1',
      cursor: 'pointer',
      fontSize: 9,
      lineHeight: '16px',
      padding: 0,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(EyeIcon, {
    size: 10,
    color: hiddenPlatforms?.has(p.id) ? '#86efac' : '#cbd5e1'
  }))))), /*#__PURE__*/React.createElement("div", {
    style: isMobile && typeof onMetricSort === 'function' ? {
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    } : undefined
  }, isMobile && typeof onMetricSort === 'function' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      order: 2
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      letterSpacing: '0.16em',
      textTransform: 'uppercase'
    }
  }, "\u0421\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u043A\u0430 \u043F\u043E \u043F\u043E\u043A\u0430\u0437\u0430\u0442\u0435\u043B\u044E"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => onToggleSortByDelta?.(),
    title: sortByDelta ? 'Сортировка по приросту включена. Нажмите — по абсолютным значениям.' : 'Сортировать по приросту выбранного показателя (дельта)',
    "aria-pressed": sortByDelta ? 'true' : 'false',
    "aria-label": sortByDelta ? 'Выключить сортировку по приросту' : 'Включить сортировку по приросту',
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      border: '1px solid ' + (sortByDelta ? accent : 'var(--line)'),
      background: sortByDelta ? `${accent}22` : 'rgba(255,255,255,0.03)',
      color: sortByDelta ? accent : 'var(--ink-mute)',
      cursor: 'pointer',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 0,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(DeltaGrowthIcon, {
    size: 15,
    color: sortByDelta ? accent : 'var(--ink-mute)'
  })), [{
    key: 'followers',
    short: 'Подп',
    title: 'Подписчики'
  }, {
    key: 'views',
    short: 'Просм',
    title: 'Просмотры'
  }, {
    key: 'likes',
    short: 'Лайки',
    title: 'Лайки'
  }, {
    key: 'posts',
    short: 'Публ',
    title: 'Публикации'
  }, {
    key: 'clicks',
    short: 'Пер',
    title: 'Переходы'
  }].map(({
    key,
    short,
    title
  }) => {
    const active = sortKey === key;
    const mark = active ? sortOrder === 'desc' ? ' ↓' : ' ↑' : '';
    const hint = active ? sortOrder === 'desc' ? `${title} — от большего к меньшему` : `${title} — от меньшего к большему` : title;
    return /*#__PURE__*/React.createElement(Pill, {
      key: key,
      active: active,
      onClick: () => onMetricSort(key),
      title: hint
    }, short, mark);
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      flexWrap: 'wrap',
      ...(isMobile && typeof onMetricSort === 'function' ? {
        order: 1
      } : {})
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: false,
    onClick: onReset
  }, isMobile ? '↻' : '↺ Сбросить фильтры'), /*#__PURE__*/React.createElement(Pill, {
    active: status === 'all',
    onClick: () => setStatus('all')
  }, isMobile ? 'Все ст.' : 'Все статусы'), /*#__PURE__*/React.createElement(Pill, {
    active: status === 'avail',
    onClick: () => setStatus('avail')
  }, isMobile ? 'Дост.' : 'Доступные'), /*#__PURE__*/React.createElement(Pill, {
    active: status === 'unavail',
    onClick: () => setStatus('unavail')
  }, isMobile ? 'Недост.' : 'Недоступные'))));
}
function Pill({
  active,
  onClick,
  children,
  dot,
  title,
  style: styleProp
}) {
  const isMobile = useIsMobile(980);
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    title: title,
    onClick: onClick,
    style: {
      minHeight: isMobile ? 40 : undefined,
      padding: isMobile ? '8px 12px' : '8px 14px',
      borderRadius: 999,
      cursor: 'pointer',
      background: active ? '#fff' : 'rgba(255,255,255,0.025)',
      color: active ? '#000' : 'var(--ink-dim)',
      border: '1px solid ' + (active ? '#fff' : 'var(--line)'),
      fontSize: isMobile ? 12 : 13,
      fontWeight: active ? 600 : 500,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      ...styleProp
    }
  }, dot && /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: 999,
      background: dot
    }
  }), children);
}
function AccountsTable({
  rows,
  accent,
  sortKey,
  sortOrder,
  setSortKey,
  setSortOrder,
  sortByDelta,
  setSortByDelta,
  onOpenAccount,
  onRefreshOne,
  onDeleteOne,
  rowBusyId
}) {
  const onSort = key => {
    if (sortKey === key) {
      setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };
  const sortMark = key => sortKey === key ? sortOrder === 'desc' ? ' ↓' : ' ↑' : '';
  const metricBtn = (key, label) => /*#__PURE__*/React.createElement("button", {
    type: "button",
    key: key,
    onClick: () => onSort(key),
    style: {
      textAlign: 'right',
      border: 'none',
      background: 'transparent',
      color: sortKey === key ? accent : 'var(--ink-mute)',
      cursor: 'pointer',
      font: 'inherit',
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      whiteSpace: 'nowrap',
      maxWidth: '100%'
    }
  }, label, sortByDelta ? ' Δ' : '', sortMark(key));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '2fr 1fr 1fr 0.8fr 1fr 0.8fr 0.8fr 0.8fr 1.1fr 1.2fr',
      padding: '10px 20px',
      gap: 16,
      borderBottom: '1px solid var(--line)',
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      fontFamily: 'JetBrains Mono, monospace',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u0410\u043A\u043A\u0430\u0443\u043D\u0442")), /*#__PURE__*/React.createElement("div", null, "\u041F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u0430"), /*#__PURE__*/React.createElement("div", null, "\u041F\u0440\u043E\u0444\u0438\u043B\u044C"), metricBtn('followers', 'Подписчики'), metricBtn('views', 'Просмотры'), metricBtn('likes', 'Лайки'), metricBtn('posts', 'Публ.'), metricBtn('clicks', 'Переходы'), /*#__PURE__*/React.createElement("div", null, "\u041E\u0431\u043D\u043E\u0432\u043B\u0451\u043D"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'flex-end',
      gap: 8,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      fontSize: 11,
      color: 'var(--ink-mute)',
      fontFamily: 'JetBrains Mono, monospace',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044F"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setSortByDelta(v => !v),
    title: sortByDelta ? 'Сортировка по приросту включена. Нажмите — по абсолютным значениям.' : 'Сортировать по приросту выбранного показателя (дельта за период снимков)',
    "aria-pressed": sortByDelta ? 'true' : 'false',
    "aria-label": sortByDelta ? 'Выключить сортировку по приросту' : 'Включить сортировку по приросту',
    style: {
      flexShrink: 0,
      width: 26,
      height: 26,
      borderRadius: 6,
      border: '1px solid ' + (sortByDelta ? accent : 'var(--line)'),
      background: sortByDelta ? `${accent}22` : 'rgba(255,255,255,0.03)',
      color: sortByDelta ? accent : 'var(--ink-mute)',
      cursor: 'pointer',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 0
    }
  }, /*#__PURE__*/React.createElement(DeltaGrowthIcon, {
    size: 13,
    color: sortByDelta ? accent : 'var(--ink-mute)'
  })))), rows.map((a, i) => /*#__PURE__*/React.createElement(AccountRow, {
    key: a.id || `${a.platform}:${a.username || a.handle}`,
    a: a,
    i: i,
    onOpenAccount: onOpenAccount,
    onRefreshOne: onRefreshOne,
    onDeleteOne: onDeleteOne,
    rowBusyId: rowBusyId
  })));
}
function AccountRow({
  a,
  i,
  onOpenAccount,
  onRefreshOne,
  onDeleteOne,
  rowBusyId
}) {
  const isMobile = useIsMobile(980);
  const meta = PLATFORM_META[a.platform] || {
    color: '#9ca3af',
    label: a.platform || 'Unknown'
  };
  const profileMeta = PROFILE_META[a.profile] || {
    color: '#525a70',
    label: 'Без профиля'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '2fr 1fr 1fr 0.8fr 1fr 0.8fr 0.8fr 0.8fr 1.1fr 1.2fr',
      padding: '16px 20px',
      gap: 16,
      alignItems: 'center',
      borderBottom: i < ACCOUNTS.length - 1 ? '1px solid var(--line)' : 'none',
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => onOpenAccount?.(a.id),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      border: 'none',
      background: 'transparent',
      padding: 0,
      textAlign: 'left',
      cursor: 'pointer',
      color: 'inherit'
    }
  }, /*#__PURE__*/React.createElement(AccountAvatar, {
    src: a.avatarUrl,
    name: a.name,
    size: 36,
    borderColor: `${meta.color}55`,
    fallbackBg: `linear-gradient(135deg, ${meta.color}40, ${profileMeta.color}30)`
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 500,
      color: '#fff'
    }
  }, a.name), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)'
    }
  }, a.handle))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: a.platform
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(ProfileBadge, {
    id: a.profile
  }), /*#__PURE__*/React.createElement(AvailabilityBadge, {
    unavailable: a.unavailable,
    reason: a.unavailableReason
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    },
    title: a.platform === 'tiktok' || a.platform === 'instagram' ? `Подписчики на профиле площадки: ${a.followers}. В снятой базе приложения: ${Number(a.audienceMembers ?? 0)}.` : 'Подписчики (число на странице профиля площадки)'
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 15,
      fontWeight: 500,
      color: Number.isFinite(Number(a.followers)) ? '#fff' : 'var(--ink-mute)'
    }
  }, Number.isFinite(Number(a.followers)) ? fmt(a.followers) : '—'), _hasDelta(a.dFollowers) && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: _deltaColor(a.dFollowers),
      textShadow: _deltaGlow(a.dFollowers)
    }
  }, a.dFollowers >= 0 ? '+' : '', fmt(a.dFollowers))), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 15,
      fontWeight: 500
    }
  }, fmt(a.views)), _hasDelta(a.dViews) && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: _deltaColor(a.dViews),
      textShadow: _deltaGlow(a.dViews)
    }
  }, a.dViews >= 0 ? '+' : '', fmt(a.dViews))), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(a.likes)), _hasDelta(a.dLikes) && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: _deltaColor(a.dLikes),
      textShadow: _deltaGlow(a.dLikes)
    }
  }, a.dLikes >= 0 ? '+' : '', fmt(a.dLikes))), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(a.posts)), _hasDelta(a.dPosts) && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: _deltaColor(a.dPosts),
      textShadow: _deltaGlow(a.dPosts)
    }
  }, a.dPosts >= 0 ? '+' : '', fmt(a.dPosts))), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    },
    title: "\u041F\u0435\u0440\u0435\u0445\u043E\u0434\u044B \u043F\u043E \u043A\u043E\u0440\u043E\u0442\u043A\u043E\u0439 \u0441\u0441\u044B\u043B\u043A\u0435 \u0438\u0437 bio (Links)"
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(a.clicks)), _hasDelta(a.dClicks) && /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 12,
      color: _deltaColor(a.dClicks),
      textShadow: _deltaGlow(a.dClicks)
    }
  }, a.dClicks >= 0 ? '+' : '', fmt(a.dClicks))), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)'
    }
  }, a.updated), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      justifyContent: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => onRefreshOne?.(a.id),
    disabled: rowBusyId === a.id,
    style: {
      minHeight: isMobile ? 40 : undefined,
      padding: isMobile ? '8px 10px' : '6px 10px',
      borderRadius: 8,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 12,
      opacity: rowBusyId === a.id ? 0.6 : 1
    }
  }, rowBusyId === a.id ? '...' : '↻'), /*#__PURE__*/React.createElement("button", {
    onClick: () => onDeleteOne?.(a.id),
    disabled: rowBusyId === a.id,
    style: {
      minHeight: isMobile ? 40 : undefined,
      padding: isMobile ? '8px 10px' : '6px 10px',
      borderRadius: 8,
      border: '1px solid #ef444455',
      background: '#ef444415',
      color: '#fca5a5',
      cursor: 'pointer',
      fontSize: 12,
      opacity: rowBusyId === a.id ? 0.6 : 1
    }
  }, "\u2715")));
}
function AccountsCards({
  rows,
  accent,
  onOpenAccount,
  onRefreshOne,
  onDeleteOne,
  rowBusyId
}) {
  const isMobile = useIsMobile(980);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 14
    }
  }, rows.map(a => {
    const meta = PLATFORM_META[a.platform] || {
      color: '#9ca3af',
      label: a.platform || 'Unknown'
    };
    const prof = PROFILE_META[a.profile] || {
      color: '#525a70',
      label: 'Без профиля'
    };
    return /*#__PURE__*/React.createElement("div", {
      key: a.id || `${a.platform}:${a.username || a.handle}`,
      style: {
        padding: 18,
        borderRadius: 14,
        background: `linear-gradient(180deg, ${prof.color}10, rgba(255,255,255,0.01))`,
        border: '1px solid var(--line)',
        position: 'relative',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: 2,
        background: prof.color,
        opacity: 0.6
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 14
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 10,
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(AccountAvatar, {
      src: a.avatarUrl,
      name: a.name,
      size: 36,
      borderColor: `${meta.color}55`,
      fallbackBg: `linear-gradient(135deg, ${meta.color}40, ${prof.color}30)`
    }), /*#__PURE__*/React.createElement("button", {
      onClick: () => onOpenAccount?.(a.id),
      style: {
        border: 'none',
        background: 'transparent',
        padding: 0,
        textAlign: 'left',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 500,
        fontSize: 14,
        color: '#fff'
      }
    }, a.name), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 11,
        color: 'var(--ink-mute)'
      }
    }, a.handle))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(ProfileBadge, {
      id: a.profile,
      dense: true
    }), /*#__PURE__*/React.createElement(AvailabilityBadge, {
      unavailable: a.unavailable,
      reason: a.unavailableReason
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
        gap: 10
      }
    }, [['Followers', a.followers, a.dFollowers, '#4ade80'], ['Views', a.views, a.dViews, '#ec4899'], ['Likes', a.likes, a.dLikes, '#f59e0b'], ['Posts', a.posts, a.dPosts, accent], ['Clicks', a.clicks, a.dClicks, '#a78bfa']].map(([l, v, d, c]) => /*#__PURE__*/React.createElement("div", {
      key: l
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 9,
        color: 'var(--ink-mute)',
        letterSpacing: '0.18em'
      }
    }, l.toUpperCase()), /*#__PURE__*/React.createElement("div", {
      className: "mono tnum",
      style: {
        fontSize: 17,
        fontWeight: 600
      }
    }, fmt(v)), _hasDelta(d) && /*#__PURE__*/React.createElement("div", {
      className: "mono tnum",
      style: {
        fontSize: 11,
        color: _deltaColor(d),
        textShadow: _deltaGlow(d)
      }
    }, d >= 0 ? '+' : '', fmt(d))))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 14,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(PlatformGlyph, {
      id: a.platform,
      size: 16
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono",
      style: {
        fontSize: 11,
        color: 'var(--ink-mute)'
      }
    }, a.updated), /*#__PURE__*/React.createElement("button", {
      onClick: () => onRefreshOne?.(a.id),
      disabled: rowBusyId === a.id,
      style: {
        padding: '5px 8px',
        borderRadius: 8,
        border: '1px solid var(--line)',
        background: 'rgba(255,255,255,0.04)',
        color: 'var(--ink)',
        cursor: 'pointer',
        fontSize: 11,
        opacity: rowBusyId === a.id ? 0.6 : 1
      }
    }, "\u21BB"), /*#__PURE__*/React.createElement("button", {
      onClick: () => onDeleteOne?.(a.id),
      disabled: rowBusyId === a.id,
      style: {
        padding: '5px 8px',
        borderRadius: 8,
        border: '1px solid #ef444455',
        background: '#ef444415',
        color: '#fca5a5',
        cursor: 'pointer',
        fontSize: 11,
        opacity: rowBusyId === a.id ? 0.6 : 1
      }
    }, "\u2715"))));
  }));
}
Object.assign(window, {
  AccountsScreen,
  TopBar,
  Sidebar,
  FilterBar
});
const {
  useState: useStateDetail,
  useEffect: useEffectDetail
} = React;
function AccountDetailScreen({
  accountId,
  onBack,
  onDataChanged
}) {
  const isMobile = useIsMobile(980);
  const [loading, setLoading] = useStateDetail(true);
  const [account, setAccount] = useStateDetail(null);
  const [posts, setPosts] = useStateDetail([]);
  const [tab, setTab] = useStateDetail('posts');
  const [busy, setBusy] = useStateDetail(false);
  const [softLoading, setSoftLoading] = useStateDetail(false);
  const [analyticsPosts, setAnalyticsPosts] = useStateDetail([]);
  const [postThumbState, setPostThumbState] = useStateDetail({});
  const [postMissingModal, setPostMissingModal] = useStateDetail(null);
  const [postDeleteBusy, setPostDeleteBusy] = useStateDetail(false);
  const load = async ({
    silent = false
  } = {}) => {
    if (silent) setSoftLoading(true);else setLoading(true);
    try {
      const [a, p] = await Promise.all([_fetchJson(`/api/accounts/${accountId}/`), _fetchJson(`/api/accounts/${accountId}/posts/`)]);
      setAccount(a);
      const postList = Array.isArray(p) ? p : [];
      setPosts(postList);
      setPostMissingModal(prev => {
        if (!prev) return null;
        const updated = postList.find(x => x.id === prev.id);
        return updated && _postScrapeNotFound(updated) ? prev : null;
      });
    } catch (e) {
      await uiAlert(`Не удалось загрузить аккаунт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      if (silent) setSoftLoading(false);else setLoading(false);
    }
  };
  useEffectDetail(() => {
    void load();
  }, [accountId]);
  const deleteMissingPost = async post => {
    if (!post?.id) return;
    if (!(await uiConfirm('Удалить публикацию из дашборда? Действие необратимо.', 'Подтверждение'))) return;
    setPostDeleteBusy(true);
    try {
      await _deleteJson(`/api/accounts/${accountId}/posts/${post.id}/`);
      setPostMissingModal(null);
      await load({
        silent: true
      });
      if (typeof onDataChanged === 'function') onDataChanged();
    } catch (e) {
      await uiAlert(`Не удалось удалить: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setPostDeleteBusy(false);
    }
  };
  const openAccountOnPlatform = () => {
    if (!account) return;
    const href = _externalProfileUrl(account.platform, account.username);
    if (!href) {
      void uiAlert('Не удалось собрать ссылку на профиль.', 'Аккаунт');
      return;
    }
    window.open(href, '_blank', 'noopener,noreferrer');
  };
  useEffectDetail(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await _fetchJson(`/api/accounts/analytics/top-posts/?period=30d&account_id=${accountId}&sort_by=view_delta&page_size=20&min_views=0`);
        if (!cancelled) setAnalyticsPosts(Array.isArray(res?.items) ? res.items : []);
      } catch {
        if (!cancelled) setAnalyticsPosts([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accountId]);
  const refreshAccount = async () => {
    setBusy(true);
    try {
      await _postJson(`/api/accounts/${accountId}/refresh/`, {});
      await load({
        silent: true
      });
      await onDataChanged?.();
    } finally {
      setBusy(false);
    }
  };
  const deleteAccount = async () => {
    if (!(await uiConfirm('Удалить аккаунт?', 'Подтвердите удаление'))) return;
    setBusy(true);
    try {
      await _delete(`/api/accounts/${accountId}/`);
      await onDataChanged?.();
      onBack?.();
    } finally {
      setBusy(false);
    }
  };
  if (loading || !account) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minHeight: '100vh',
        padding: 28,
        color: 'var(--ink-mute)'
      }
    }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430...");
  }
  const profileLabel = PROFILE_META[String(account.profile_id)]?.label || account.profile_name || 'Без профиля';
  const isUnavailable = !!(account.profile_unavailable || account.unavailable);
  const unavailableReason = String(account.profile_unavailable_reason || account.unavailable_reason || '');
  const externalProfileUrl = _externalProfileUrl(account.platform, account.username);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      padding: isMobile ? '14px 12px 28px' : '28px 36px 80px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onBack,
    style: {
      border: 'none',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u2190 \u0410\u043A\u043A\u0430\u0443\u043D\u0442\u044B"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center'
    }
  }, (busy || softLoading) && /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.08em'
    }
  }, "\u041E\u0411\u041D\u041E\u0412\u041B\u0415\u041D\u0418\u0415..."), /*#__PURE__*/React.createElement("button", {
    onClick: refreshAccount,
    disabled: busy,
    style: {
      padding: '8px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      opacity: busy ? 0.7 : 1
    }
  }, busy ? '↻ Обновление...' : '↻ Обновить'), /*#__PURE__*/React.createElement("button", {
    onClick: deleteAccount,
    disabled: busy,
    style: {
      padding: '8px 14px',
      borderRadius: 10,
      border: '1px solid #ef444455',
      background: '#ef444415',
      color: '#fca5a5',
      cursor: 'pointer'
    }
  }, "\u2715 \u0423\u0434\u0430\u043B\u0438\u0442\u044C"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement(AccountAvatar, {
    src: _accountAvatarSrc(account),
    name: String(account.display_name || account.username || '?'),
    size: 58,
    borderColor: "rgba(106,169,255,0.35)",
    fallbackBg: "linear-gradient(135deg, #6aa9ff40, #ec489940)"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 28,
      fontWeight: 700
    }
  }, account.display_name || account.username), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      color: 'var(--ink-mute)',
      fontSize: 13
    }
  }, externalProfileUrl ? /*#__PURE__*/React.createElement("a", {
    href: externalProfileUrl,
    target: "_blank",
    rel: "noopener noreferrer",
    style: {
      color: '#93c5fd',
      textDecoration: 'none',
      borderBottom: '1px dashed rgba(147,197,253,0.45)'
    },
    title: `Открыть профиль ${account.username} на ${account.platform_label || account.platform}`
  }, "@", account.username) : `@${account.username}`, " \xB7 ", account.platform_label || account.platform, " \xB7 ", profileLabel), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6
    }
  }, /*#__PURE__*/React.createElement(AvailabilityBadge, {
    unavailable: isUnavailable,
    reason: unavailableReason
  })), account.bio ? /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 13,
      marginTop: 4
    }
  }, account.bio) : null)), isUnavailable && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14,
      padding: '10px 12px',
      borderRadius: 10,
      border: '1px solid rgba(239,68,68,0.35)',
      background: 'rgba(239,68,68,0.12)',
      color: '#fecaca',
      fontSize: 13
    }
  }, "\u0410\u043A\u043A\u0430\u0443\u043D\u0442 \u0441\u0435\u0439\u0447\u0430\u0441 \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D \u0434\u043B\u044F \u0441\u0431\u043E\u0440\u0430 \u0434\u0430\u043D\u043D\u044B\u0445.", unavailableReason ? ` Причина: ${unavailableReason}` : ''), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(5, minmax(100px, 1fr))',
      gap: 10,
      marginBottom: 16
    }
  }, [['Подписчики', Number(account.follower_count || 0), Number(account.follower_delta || 0)], ['Просмотры', Number(account.view_count || 0), Number(account.view_delta || 0)], ['Лайки', Number(account.like_count || 0), Number(account.like_delta || 0)], ['Публикации', Number(account.post_count || 0), Number(account.post_delta || 0)], ['Переходы', Number(account.link_click_count || 0), Number(account.link_click_delta || 0)]].map(([label, val, delta]) => /*#__PURE__*/React.createElement("div", {
    key: label,
    style: {
      border: '1px solid var(--line)',
      borderRadius: 12,
      background: 'rgba(255,255,255,0.02)',
      padding: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink-mute)'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: 26,
      fontWeight: 700
    }
  }, fmt(val)), _hasDelta(delta) && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: Number(delta) >= 0 ? '#4ade80' : '#fca5a5'
    }
  }, Number(delta) >= 0 ? '+' : '', fmt(Number(delta)))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: tab === 'posts',
    onClick: () => setTab('posts')
  }, "\u041F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u0438 (", posts.length, ")"), /*#__PURE__*/React.createElement(Pill, {
    active: tab === 'analytics',
    onClick: () => setTab('analytics')
  }, "\u0410\u043D\u0430\u043B\u0438\u0442\u0438\u043A\u0430")), tab === 'posts' ? posts.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0435\u0442 \u043F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u0439.") : /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
      gap: 12
    }
  }, posts.map((p, idx) => {
    const thumbKey = String(p.id || p.external_id || p.post_url || idx);
    const thumbState = postThumbState[thumbKey] || 'idle';
    const postHref = _postOpenUrl(account.platform, account.username, p.external_id, p.post_url);
    const scrapeMissing = _postScrapeNotFound(p);
    return /*#__PURE__*/React.createElement("div", {
      key: thumbKey,
      role: postHref ? 'link' : undefined,
      tabIndex: postHref ? 0 : undefined,
      title: postHref ? 'Открыть публикацию на площадке' : undefined,
      onClick: () => {
        if (postHref) _openPostInNewTab(account.platform, account.username, p.external_id, p.post_url);
      },
      onKeyDown: e => {
        if (!postHref) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _openPostInNewTab(account.platform, account.username, p.external_id, p.post_url);
        }
      },
      style: {
        border: scrapeMissing ? '1px solid rgba(251,146,60,0.45)' : '1px solid var(--line)',
        borderRadius: 12,
        overflow: 'hidden',
        background: scrapeMissing ? 'rgba(251,146,60,0.06)' : 'rgba(255,255,255,0.02)',
        cursor: postHref ? 'pointer' : 'default'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        height: 160,
        background: 'rgba(15,23,42,0.7)'
      }
    }, scrapeMissing ? /*#__PURE__*/React.createElement("button", {
      type: "button",
      title: "\u041D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u043F\u0440\u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438 \u2014 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \u0434\u043B\u044F \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0439",
      "aria-label": "\u041F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u044F \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u0430 \u043F\u0440\u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438",
      onClick: e => {
        e.preventDefault();
        e.stopPropagation();
        setPostMissingModal(p);
      },
      style: {
        position: 'absolute',
        top: 6,
        right: 6,
        zIndex: 3,
        padding: 6,
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(ScrapeMissingDot, null)) : null, _postShowsThumbnail(p) && /*#__PURE__*/React.createElement("img", {
      src: _postThumbnailSrc(p),
      alt: "",
      loading: "lazy",
      decoding: "async",
      onLoad: () => setPostThumbState(prev => ({
        ...prev,
        [thumbKey]: 'loaded'
      })),
      onError: () => setPostThumbState(prev => ({
        ...prev,
        [thumbKey]: 'error'
      })),
      style: {
        width: '100%',
        height: 160,
        objectFit: 'cover',
        display: 'block',
        opacity: thumbState === 'loaded' ? 1 : 0,
        transition: 'opacity 220ms ease'
      }
    }), _postShowsThumbnail(p) && thumbState !== 'loaded' && thumbState !== 'error' && /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        position: 'absolute',
        inset: 0,
        display: 'grid',
        placeItems: 'center',
        color: 'var(--ink-mute)',
        fontSize: 11
      }
    }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430..."), (!_postShowsThumbnail(p) || thumbState === 'error') && /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        inset: 0,
        display: 'grid',
        placeItems: 'center',
        color: 'var(--ink-mute)'
      }
    }, "NO IMAGE")), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: 'var(--ink-dim)',
        minHeight: 36
      }
    }, String(p.description || '').slice(0, 90)), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        marginTop: 8,
        fontSize: 12,
        color: 'var(--ink-mute)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4
      }
    }, /*#__PURE__*/React.createElement(EyeIcon, {
      size: 12,
      color: "currentColor"
    }), " ", fmt(Number(p.view_count || 0))), " \xB7 \u2665 ", fmt(Number(p.like_count || 0)))));
  })) : analyticsPosts.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0435\u0442 \u0434\u0430\u043D\u043D\u044B\u0445 \u0430\u043D\u0430\u043B\u0438\u0442\u0438\u043A\u0438.") : /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, analyticsPosts.map((p, i) => {
    const pl = p?.account?.platform || account.platform;
    const un = p?.account?.username || account.username;
    const postHref = _postOpenUrl(pl, un, p.external_id, p.post_url);
    const scrapeMissing = _postScrapeNotFound(p);
    return /*#__PURE__*/React.createElement("div", {
      key: p.id || i,
      role: postHref ? 'link' : undefined,
      tabIndex: postHref ? 0 : undefined,
      title: postHref ? 'Открыть публикацию на площадке' : undefined,
      onClick: () => {
        if (postHref) _openPostInNewTab(pl, un, p.external_id, p.post_url);
      },
      onKeyDown: e => {
        if (!postHref) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _openPostInNewTab(pl, un, p.external_id, p.post_url);
        }
      },
      style: {
        border: scrapeMissing ? '1px solid rgba(251,146,60,0.45)' : '1px solid var(--line)',
        borderRadius: 12,
        background: scrapeMissing ? 'rgba(251,146,60,0.06)' : 'rgba(255,255,255,0.02)',
        padding: 12,
        cursor: postHref ? 'pointer' : 'default',
        position: 'relative'
      }
    }, scrapeMissing ? /*#__PURE__*/React.createElement("button", {
      type: "button",
      title: "\u041D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u043F\u0440\u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438 \u2014 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \u0434\u043B\u044F \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0439",
      "aria-label": "\u041F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u044F \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u0430 \u043F\u0440\u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438",
      onClick: e => {
        e.preventDefault();
        e.stopPropagation();
        setPostMissingModal(p);
      },
      style: {
        position: 'absolute',
        top: 6,
        right: 6,
        zIndex: 2,
        padding: 6,
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(ScrapeMissingDot, null)) : null, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        gap: 12,
        paddingRight: scrapeMissing ? 28 : 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        color: 'var(--ink-dim)',
        fontSize: 13
      }
    }, String(p.description || '').slice(0, 120)), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        color: '#4ade80',
        fontSize: 12
      }
    }, "+", fmt(Number(p.view_delta || 0)))));
  })), postMissingModal ? /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 95,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.72)',
      padding: 16
    },
    onClick: e => {
      if (e.target === e.currentTarget && !postDeleteBusy) setPostMissingModal(null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": true,
    "aria-labelledby": "post-missing-modal-title",
    style: {
      width: '100%',
      maxWidth: 440,
      borderRadius: 16,
      border: '1px solid rgba(251,146,60,0.45)',
      background: 'rgba(18,20,28,0.98)',
      padding: 20,
      boxShadow: '0 24px 56px rgba(0,0,0,0.65)'
    },
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(ScrapeMissingDot, {
    size: 8,
    style: {
      marginTop: 6
    }
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    id: "post-missing-modal-title",
    style: {
      margin: 0,
      fontSize: 17,
      color: '#fff'
    }
  }, "\u041F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u044F \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '10px 0 0',
      fontSize: 13,
      color: 'var(--ink-mute)',
      lineHeight: 1.5
    }
  }, "\u041F\u0440\u0438 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0435\u043C \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438 \u044D\u0442\u043E\u0439 \u043F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u0438 \u043D\u0435 \u0431\u044B\u043B\u043E \u0432 \u043E\u0442\u0432\u0435\u0442\u0435 \u0441\u043A\u0440\u0430\u043F\u0435\u0440\u0430. \u041E\u043D\u0430 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0430 \u0432 \u0434\u0430\u0448\u0431\u043E\u0440\u0434\u0435. \u041E\u0442\u043A\u0440\u043E\u0439\u0442\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u044C \u043D\u0430 \u043F\u043B\u043E\u0449\u0430\u0434\u043A\u0435 \u0438 \u043F\u0440\u043E\u0432\u0435\u0440\u044C\u0442\u0435 \u0432\u0440\u0443\u0447\u043D\u0443\u044E \u2014 \u0437\u0430\u0442\u0435\u043C \u0443\u0434\u0430\u043B\u0438\u0442\u0435 \u0437\u0430\u043F\u0438\u0441\u044C \u0437\u0434\u0435\u0441\u044C, \u0435\u0441\u043B\u0438 \u043F\u043E\u0441\u0442\u0430 \u0431\u043E\u043B\u044C\u0448\u0435 \u043D\u0435\u0442."), postMissingModal.external_id ? /*#__PURE__*/React.createElement("p", {
    className: "mono",
    style: {
      margin: '8px 0 0',
      fontSize: 11,
      color: 'var(--ink-dim)'
    }
  }, "ID: ", String(postMissingModal.external_id)) : null)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: isMobile ? 'column' : 'row',
      gap: 10,
      justifyContent: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: postDeleteBusy,
    onClick: () => setPostMissingModal(null),
    style: {
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: postDeleteBusy ? 'default' : 'pointer',
      opacity: postDeleteBusy ? 0.6 : 1
    }
  }, "\u0417\u0430\u043A\u0440\u044B\u0442\u044C"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: postDeleteBusy,
    onClick: () => openAccountOnPlatform(),
    style: {
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid rgba(106,169,255,0.45)',
      background: 'rgba(106,169,255,0.12)',
      color: '#93c5fd',
      cursor: postDeleteBusy ? 'default' : 'pointer',
      opacity: postDeleteBusy ? 0.6 : 1
    }
  }, "\u041F\u0435\u0440\u0435\u0439\u0442\u0438 \u0432 \u0430\u043A\u043A\u0430\u0443\u043D\u0442"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: postDeleteBusy,
    onClick: () => {
      void deleteMissingPost(postMissingModal);
    },
    style: {
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid rgba(239,68,68,0.45)',
      background: 'rgba(239,68,68,0.15)',
      color: '#fca5a5',
      cursor: postDeleteBusy ? 'default' : 'pointer',
      opacity: postDeleteBusy ? 0.6 : 1
    }
  }, postDeleteBusy ? 'Удаление…' : 'Удалить')))) : null);
}

// ===== screen-analytics.jsx =====

// Analytics screen — atomic-themed redesign of "Аналитика" tab.

const {
  useState: useStateAn,
  useEffect: useEffectAn
} = React;
function AnalyticsScreen({
  tweaks,
  onOpenGlobalModal,
  onOpenAccount
}) {
  const isMobile = useIsMobile(980);
  const accent = tweaks.accent || '#6aa9ff';
  const pageSize = isMobile ? 5 : 20;
  const [period, setPeriod] = useStateAn('1d');
  const [platform, setPlatform] = useStateAn('all');
  const [scrapeFilter, setScrapeFilter] = useStateAn('active');
  const [sortBy, setSortBy] = useStateAn('view_delta');
  const [minViews, setMinViews] = useStateAn(10);
  const [hashtagSort, setHashtagSort] = useStateAn('count');
  const [topPosts, setTopPosts] = useStateAn([]);
  const [page, setPage] = useStateAn(1);
  const [pages, setPages] = useStateAn(1);
  const [totalPosts, setTotalPosts] = useStateAn(0);
  const [insights, setInsights] = useStateAn(null);
  const [loading, setLoading] = useStateAn(false);
  const [initialReady, setInitialReady] = useStateAn(false);
  useEffectAn(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          period,
          sort_by: sortBy,
          page_size: String(pageSize),
          page: String(page),
          min_views: String(minViews)
        });
        if (platform !== 'all') params.set('platform', platform);
        if (scrapeFilter === 'missing') {
          params.set('scrape_filter', 'missing');
          if (minViews > 0) params.set('min_views', String(minViews));else params.set('min_views', '0');
        } else {
          params.set('scrape_filter', 'active');
          params.set('min_views', String(minViews));
        }
        const insightsUrl = `/api/accounts/analytics/insights/?period=${encodeURIComponent(period)}${platform !== 'all' ? `&platform=${encodeURIComponent(platform)}` : ''}&min_views=${encodeURIComponent(String(minViews))}&scrape_filter=active`;
        const [res, insightsRes] = await Promise.all([_fetchJson(`/api/accounts/analytics/top-posts/?${params.toString()}`), scrapeFilter === 'missing' ? Promise.resolve(null) : _fetchJson(insightsUrl).catch(() => null)]);
        const mapped = Array.isArray(res?.items) ? res.items.map(p => ({
          handle: p?.account?.platform === 'rumble' ? String(p?.account?.username || '') : `@${String(p?.account?.username || '')}`,
          username: String(p?.account?.username || ''),
          platform: String(p?.account?.platform || ''),
          accountId: Number(p?.account?.id || 0) || null,
          postId: Number(p?.id || 0) || null,
          date: _ruShortDate(p?.posted_at || '').slice(0, 8).replace(/\./g, '.'),
          missingSince: p?.missing_from_scrape_at ? _ruShortDate(String(p.missing_from_scrape_at)) : '',
          text: String(p?.description || ''),
          delta: Number(p?.view_delta || 0),
          views: Number(p?.view_count || 0),
          likes: Number(p?.like_count || 0),
          er: Number(p?.engagement_rate || 0),
          thumb: _postThumbnailSrc(p),
          postUrl: String(p?.post_url || ''),
          externalId: String(p?.external_id || ''),
          scrapeNotFound: Boolean(p?.scrape_not_found || p?.missing_from_scrape_at)
        })) : [];
        if (!cancelled) {
          setTopPosts(mapped);
          setPages(Math.max(1, Number(res?.pages || 1)));
          setTotalPosts(Math.max(0, Number(res?.total || 0)));
          setInsights(insightsRes && typeof insightsRes === 'object' ? insightsRes : null);
          setInitialReady(true);
        }
      } catch {
        if (!cancelled) {
          setTopPosts([]);
          setPages(1);
          setTotalPosts(0);
          setInsights(null);
          setInitialReady(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [period, platform, scrapeFilter, sortBy, page, minViews, pageSize]);
  React.useEffect(() => {
    setPage(1);
  }, [period, platform, scrapeFilter, sortBy, minViews]);
  const sortOptions = [{
    id: 'view_delta',
    label: 'Прирост просмотров'
  }, {
    id: 'like_delta',
    label: 'Прирост лайков'
  }, {
    id: 'views',
    label: 'Просмотры (всего)'
  }, {
    id: 'likes',
    label: 'Лайки (всего)'
  }, {
    id: 'er',
    label: 'Вовлеченность (ER)'
  }];
  const analyticsRows = topPosts;
  const safeRows = analyticsRows.length > 0 ? analyticsRows : [{
    delta: 0,
    views: 0,
    er: 0
  }];
  const hourRows = Array.isArray(insights?.best_hours) ? insights.best_hours : [];
  const platformRows = Array.isArray(insights?.platform_comparison) ? insights.platform_comparison : [];
  const totalDelta = platformRows.reduce((acc, r) => acc + Number(r.avg_views || 0) * Number(r.post_count || 0), 0);
  const totalPostsCount = platformRows.reduce((acc, r) => acc + Number(r.post_count || 0), 0);
  const avgEr = totalPostsCount > 0 ? platformRows.reduce((acc, r) => acc + Number(r.avg_er || 0) * Number(r.post_count || 0), 0) / totalPostsCount : safeRows.reduce((acc, p) => acc + Number(p.er || 0), 0) / Math.max(1, safeRows.length);
  const engagementSpark = hourRows.length > 0 ? hourRows.map(h => Math.max(0, Number(h.avg_views || 0))) : safeRows.map(p => Math.max(0, Number(p.delta || 0))).reverse();
  const viewsSpark = hourRows.length > 0 ? hourRows.map(h => Math.max(0, Number(h.avg_views || 0))) : safeRows.map(p => Math.max(0, Number(p.views || 0))).reverse();
  const erSpark = hourRows.length > 0 ? hourRows.map(h => Number(h.avg_er || 0)) : safeRows.map(p => Number(p.er || 0));
  const postDeltas = safeRows.map(p => Math.max(0, Number(p.delta || 0))).filter(v => Number.isFinite(v));
  const viralitySpark = postDeltas.length > 0 ? postDeltas.slice().reverse() : hourRows.length > 0 ? hourRows.map(h => Number(h.avg_views || 0)) : [0, 0];
  const viralCount = postDeltas.filter(v => v >= 200).length;
  const maxPostDelta = postDeltas.length > 0 ? Math.max(...postDeltas) : 0;
  let viralityLevel = 'LOW';
  if (maxPostDelta >= 1000) viralityLevel = 'VERY HIGH';else if (maxPostDelta >= 500) viralityLevel = 'HIGH';else if (maxPostDelta >= 200) viralityLevel = 'MEDIUM';
  const platformComparison = platformRows;
  const topHashtagsRaw = Array.isArray(insights?.top_hashtags) ? insights.top_hashtags : [];
  const bestHours = Array.isArray(insights?.best_hours) ? insights.best_hours : [];
  const bestWeekdays = Array.isArray(insights?.best_weekdays) ? insights.best_weekdays : [];
  const hashtagSorted = [...topHashtagsRaw].sort((a, b) => {
    const av = Number(a?.[hashtagSort] || 0);
    const bv = Number(b?.[hashtagSort] || 0);
    return bv - av;
  }).slice(0, 20);
  const maxHourViews = Math.max(1, ...bestHours.map(h => Number(h.avg_views || 0)));
  const maxWeekdayViews = Math.max(1, ...bestWeekdays.map(d => Number(d.avg_views || 0)));
  if (!initialReady) {
    return /*#__PURE__*/React.createElement("div", {
      style: _pageShellStyle(),
      "data-screen-label": "Analytics"
    }, /*#__PURE__*/React.createElement(TopBar, {
      accent: accent,
      onRefreshAll: () => onOpenGlobalModal?.('refresh_all'),
      onOpenSchedule: () => onOpenGlobalModal?.('schedule'),
      onOpenAddList: () => onOpenGlobalModal?.('add_list'),
      onOpenAddOne: () => onOpenGlobalModal?.('add_one')
    }), /*#__PURE__*/React.createElement("main", {
      style: _embedShellStyle(isMobile)
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : '1.6fr 1fr 1fr 1fr',
        gap: 12,
        marginBottom: 18
      }
    }, [0, 1, 2, 3].map(i => /*#__PURE__*/React.createElement("div", {
      key: `an-sk-${i}`,
      style: {
        height: isMobile && i > 0 ? 128 : 186,
        borderRadius: 16,
        border: '1px solid var(--line)',
        background: 'linear-gradient(90deg, rgba(255,255,255,0.015) 0%, rgba(255,255,255,0.055) 45%, rgba(255,255,255,0.015) 100%)',
        backgroundSize: '220% 100%',
        animation: 'anShimmer 1.4s linear infinite'
      }
    }))), /*#__PURE__*/React.createElement("style", null, `@keyframes anShimmer { 0% { background-position: 220% 0; } 100% { background-position: -220% 0; } }`)));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: _pageShellStyle(),
    "data-screen-label": "Analytics"
  }, /*#__PURE__*/React.createElement(TopBar, {
    accent: accent,
    onRefreshAll: () => onOpenGlobalModal?.('refresh_all'),
    onOpenSchedule: () => onOpenGlobalModal?.('schedule'),
    onOpenAddList: () => onOpenGlobalModal?.('add_list'),
    onOpenAddOne: () => onOpenGlobalModal?.('add_one')
  }), /*#__PURE__*/React.createElement("main", {
    style: _embedShellStyle(isMobile, {
      animation: 'anFadeIn .24s ease-out'
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '1.6fr 1fr 1fr 1fr',
      gap: 12,
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 24,
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink-dim)',
      fontWeight: 500,
      letterSpacing: 0
    }
  }, "\u0412\u043E\u0432\u043B\u0435\u0447\u0435\u043D\u043D\u043E\u0441\u0442\u044C"), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.16em'
    }
  }, period === '1d' ? '24H' : period.toUpperCase())), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 10,
      right: 10
    }
  }, /*#__PURE__*/React.createElement(InfoButton, {
    onClick: () => uiAlert('Вовлеченность отражает суммарную динамику просмотров по реальным данным из аналитики за выбранный период.', 'Вовлеченность'),
    title: "\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435: \u0412\u043E\u0432\u043B\u0435\u0447\u0435\u043D\u043D\u043E\u0441\u0442\u044C",
    size: 11
  })), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: isMobile ? 46 : 64,
      fontWeight: 700,
      lineHeight: 1,
      marginTop: 8,
      letterSpacing: '-0.02em'
    }
  }, fmt(totalDelta)), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      marginTop: 4,
      fontSize: 14,
      color: '#4ade80'
    }
  }, "\u25B2 \u0434\u0438\u043D\u0430\u043C\u0438\u043A\u0430 \u043F\u043E \u0440\u0435\u0430\u043B\u044C\u043D\u044B\u043C \u0434\u0430\u043D\u043D\u044B\u043C"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      height: 60
    }
  }, /*#__PURE__*/React.createElement(Sparkline, {
    data: engagementSpark.length > 1 ? engagementSpark : TREND_24H,
    color: accent,
    width: isMobile ? 320 : 500,
    height: 60
  }))), [{
    l: 'Топ постов',
    v: String(totalPostsCount || analyticsRows.length),
    d: `${fmt(totalDelta)} / ${period === '1d' ? '24h' : period.toUpperCase()}`,
    c: '#ec4899',
    spark: viewsSpark,
    infoTitle: 'Топ постов',
    infoText: 'График показывает тренд просмотров в блоке топ-постов за выбранный период.'
  }, {
    l: 'Средний ER',
    v: `${avgEr.toFixed(1)}%`,
    d: `${analyticsRows.length} постов`,
    c: '#f59e0b',
    spark: erSpark,
    infoTitle: 'Средний ER',
    infoText: 'График показывает изменение среднего ER (engagement rate) за выбранный период.'
  }, {
    l: 'Вирусность',
    v: viralityLevel,
    d: `${viralCount} поста >+200 · пик +${fmt(maxPostDelta)}`,
    c: '#4ade80',
    spark: viralitySpark,
    infoTitle: 'Вирусность',
    infoText: 'Уровень вирусности считается по реальному приросту просмотров постов (view_delta): MEDIUM от +200, HIGH от +500, VERY HIGH от +1000.'
  }].map(s => /*#__PURE__*/React.createElement("div", {
    key: s.l,
    style: {
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 20,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 10,
      right: 10
    }
  }, /*#__PURE__*/React.createElement(InfoButton, {
    onClick: () => uiAlert(String(s.infoText || ''), String(s.infoTitle || s.l)),
    title: `Подробнее: ${s.l}`,
    size: 11
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink-dim)',
      fontWeight: 500
    }
  }, s.l), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: isMobile ? 30 : 36,
      fontWeight: 700,
      marginTop: 8,
      letterSpacing: '-0.02em'
    }
  }, s.v), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 12,
      color: s.c,
      marginTop: 4
    }
  }, s.d), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      height: 36
    }
  }, /*#__PURE__*/React.createElement(Sparkline, {
    data: Array.isArray(s.spark) && s.spark.length > 1 ? s.spark : TREND_24H.map(v => v * 0.4),
    color: s.c,
    width: isMobile ? 360 : 220,
    height: 36,
    dot: false,
    stretch: true
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginBottom: 18,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      padding: 4,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)'
    }
  }, [['1d', 'Сутки'], ['7d', '7 дней'], ['30d', '30 дней']].map(([id, l]) => /*#__PURE__*/React.createElement("button", {
    key: id,
    onClick: () => setPeriod(id),
    style: {
      padding: '8px 14px',
      borderRadius: 9,
      border: 'none',
      cursor: 'pointer',
      background: period === id ? '#fff' : 'transparent',
      color: period === id ? '#000' : 'var(--ink-dim)',
      fontSize: 13,
      fontWeight: 500
    }
  }, l))), /*#__PURE__*/React.createElement(Pill, {
    active: platform === 'all',
    onClick: () => setPlatform('all')
  }, "\u0412\u0441\u0435"), PLATFORMS.map(p => /*#__PURE__*/React.createElement(Pill, {
    key: p.id,
    active: platform === p.id,
    onClick: () => setPlatform(p.id),
    dot: isMobile ? undefined : p.color
  }, isMobile ? /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: p.id,
    size: 14
  }) : p.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16,
      flexWrap: 'wrap',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.12em'
    }
  }, "\u041F\u041E\u0421\u0422\u042B"), /*#__PURE__*/React.createElement(Pill, {
    active: scrapeFilter === 'active',
    onClick: () => setScrapeFilter('active')
  }, "\u0410\u043A\u0442\u0438\u0432\u043D\u044B\u0435 \u0432 \u0441\u044A\u0451\u043C\u0435"), /*#__PURE__*/React.createElement(Pill, {
    active: scrapeFilter === 'missing',
    onClick: () => setScrapeFilter('missing'),
    style: scrapeFilter === 'missing' ? {
      borderColor: 'rgba(251,146,60,0.65)',
      background: 'rgba(251,146,60,0.22)',
      color: '#ffedd5'
    } : undefined
  }, /*#__PURE__*/React.createElement(ScrapeMissingDot, null), "\u0412\u043E\u0437\u043C\u043E\u0436\u043D\u043E \u0443\u0434\u0430\u043B\u0451\u043D\u043D\u044B\u0435")), /*#__PURE__*/React.createElement(SectionHeader, {
    kicker: scrapeFilter === 'missing' ? 'ВОЗМОЖНО УДАЛЕНЫ' : 'TOP MOVERS',
    title: /*#__PURE__*/React.createElement(React.Fragment, null, scrapeFilter === 'missing' ? 'Посты не найдены при обновлении' : 'Топ постов', /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--ink-mute)',
        fontWeight: 400,
        marginLeft: 8
      }
    }, "(", totalPosts || topPosts.length, ")")),
    right: /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, loading && /*#__PURE__*/React.createElement("span", {
      className: "mono",
      style: {
        fontSize: 11,
        color: 'var(--ink-mute)'
      }
    }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430..."), /*#__PURE__*/React.createElement("select", {
      value: String(minViews),
      onChange: e => setMinViews(Math.max(0, Number(e.target.value || 0))),
      title: "\u041C\u0438\u043D\u0438\u043C\u0443\u043C \u043F\u0440\u043E\u0441\u043C\u043E\u0442\u0440\u043E\u0432 \u0434\u043B\u044F \u0442\u043E\u043F\u0430 \u043F\u043E\u0441\u0442\u043E\u0432",
      style: {
        minWidth: isMobile ? 140 : 160,
        padding: '8px 10px',
        borderRadius: 10,
        border: '1px solid var(--line)',
        background: 'rgba(148,163,184,0.16)',
        color: '#ffffff',
        fontSize: 14,
        fontFamily: 'inherit',
        cursor: 'pointer'
      }
    }, [0, 10, 25, 50, 100, 250, 500, 1000].map(v => /*#__PURE__*/React.createElement("option", {
      key: v,
      value: String(v),
      style: {
        color: '#ffffff',
        background: '#374151'
      }
    }, "\u041C\u0438\u043D: ", v, "+"))), scrapeFilter !== 'missing' ? /*#__PURE__*/React.createElement("select", {
      value: sortBy,
      onChange: e => setSortBy(String(e.target.value || 'view_delta')),
      style: {
        minWidth: isMobile ? 180 : 240,
        padding: '8px 10px',
        borderRadius: 10,
        border: '1px solid var(--line)',
        background: 'rgba(148,163,184,0.16)',
        color: '#ffffff',
        fontSize: 14,
        fontFamily: 'inherit',
        cursor: 'pointer'
      }
    }, sortOptions.map(o => /*#__PURE__*/React.createElement("option", {
      key: o.id,
      value: o.id,
      style: {
        color: '#ffffff',
        background: '#374151'
      }
    }, o.label))) : null)
  }), scrapeFilter === 'missing' ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 12px',
      fontSize: 13,
      color: 'rgba(251,191,36,0.92)',
      lineHeight: 1.45
    }
  }, "\u041F\u043E\u0441\u0442\u044B, \u043A\u043E\u0442\u043E\u0440\u044B\u0435 \u043D\u0435 \u043F\u043E\u043F\u0430\u043B\u0438 \u0432 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0438\u0439 \u0441\u044A\u0451\u043C \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430. \u0421\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u043A\u0430 \u2014 \u043F\u043E \u0434\u0430\u0442\u0435 \u043F\u043E\u043C\u0435\u0442\u043A\u0438 (\u043D\u043E\u0432\u044B\u0435 \u0441\u0432\u0435\u0440\u0445\u0443). \u041E\u0442\u043A\u0440\u043E\u0439\u0442\u0435 \u043A\u0430\u0440\u0442\u043E\u0447\u043A\u0443 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430 \u0434\u043B\u044F \u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0438 \u0438 \u0443\u0434\u0430\u043B\u0435\u043D\u0438\u044F.") : null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
      gap: 10
    }
  }, topPosts.map((p, i) => /*#__PURE__*/React.createElement(PostRow, {
    key: `${p.postId || p.postUrl || p.handle}-${i}`,
    p: p,
    accent: accent,
    rank: (page - 1) * pageSize + i + 1,
    max: topPosts[0]?.delta || 1,
    isMobile: isMobile,
    onOpenAccount: onOpenAccount
  })))), topPosts.length === 0 && !loading && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      borderRadius: 12,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 14,
      fontSize: 13,
      color: 'var(--ink-mute)'
    }
  }, scrapeFilter === 'missing' ? 'Нет постов с пометкой «не найден при обновлении» для выбранных фильтров.' : 'Нет данных для выбранных фильтров.'), /*#__PURE__*/React.createElement("style", null, `@keyframes anFadeIn { from { opacity: 0; } to { opacity: 1; } }`), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      gap: 10,
      marginTop: 12,
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setPage(v => Math.max(1, v - 1)),
    disabled: page <= 1,
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: page <= 1 ? 'default' : 'pointer',
      opacity: page <= 1 ? 0.45 : 1
    }
  }, "\u2190 \u041D\u0430\u0437\u0430\u0434"), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)'
    }
  }, "\u0421\u0442\u0440. ", page, " / ", pages), /*#__PURE__*/React.createElement("button", {
    onClick: () => setPage(v => Math.min(pages, v + 1)),
    disabled: page >= pages,
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: page >= pages ? 'default' : 'pointer',
      opacity: page >= pages ? 0.45 : 1
    }
  }, "\u0412\u043F\u0435\u0440\u0435\u0434 \u2192")), scrapeFilter !== 'missing' ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20,
      display: 'grid',
      gridTemplateColumns: '1fr',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px 16px',
      borderBottom: '1px solid var(--line)',
      fontWeight: 600
    }
  }, "\u0421\u0440\u0430\u0432\u043D\u0435\u043D\u0438\u0435 \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C"), /*#__PURE__*/React.createElement("div", {
    style: {
      overflowX: 'auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 620
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      display: 'grid',
      gridTemplateColumns: '1.4fr 0.8fr 0.8fr 0.8fr 0.8fr',
      gap: 10,
      padding: '10px 16px',
      fontSize: 11,
      color: 'var(--ink-mute)',
      borderBottom: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("div", null, "\u041F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u0430"), /*#__PURE__*/React.createElement("div", null, "\u041F\u043E\u0441\u0442\u043E\u0432"), /*#__PURE__*/React.createElement("div", null, "Avg \u043F\u0440\u043E\u0441\u043C\u043E\u0442\u0440\u044B"), /*#__PURE__*/React.createElement("div", null, "Avg \u043B\u0430\u0439\u043A\u0438"), /*#__PURE__*/React.createElement("div", null, "Avg ER")), (platformComparison.length > 0 ? platformComparison : []).map((r, idx) => /*#__PURE__*/React.createElement("div", {
    key: `${r.platform}-${idx}`,
    style: {
      display: 'grid',
      gridTemplateColumns: '1.4fr 0.8fr 0.8fr 0.8fr 0.8fr',
      gap: 10,
      padding: '10px 16px',
      borderBottom: '1px solid rgba(255,255,255,0.04)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: r.platform,
    size: 13
  }), /*#__PURE__*/React.createElement("span", null, r.platform_label || r.platform)), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(Number(r.post_count || 0))), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(Number(r.avg_views || 0))), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum"
  }, fmt(Number(r.avg_likes || 0))), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      color: '#4ade80'
    }
  }, Number(r.avg_er || 0).toFixed(1), "%"))), platformComparison.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 16px',
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0435\u0442 \u0434\u0430\u043D\u043D\u044B\u0445 \u043F\u043E \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u0430\u043C.")))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      marginBottom: 10
    }
  }, "\u0422\u043E\u043F \u0445\u0435\u0448\u0442\u0435\u0433\u043E\u0432"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap',
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: hashtagSort === 'count',
    onClick: () => setHashtagSort('count')
  }, "\u041F\u043E\u0441\u0442\u043E\u0432"), /*#__PURE__*/React.createElement(Pill, {
    active: hashtagSort === 'avg_views',
    onClick: () => setHashtagSort('avg_views')
  }, "\u041F\u0440\u043E\u0441\u043C\u043E\u0442\u0440\u044B"), /*#__PURE__*/React.createElement(Pill, {
    active: hashtagSort === 'avg_likes',
    onClick: () => setHashtagSort('avg_likes')
  }, "\u041B\u0430\u0439\u043A\u0438"), /*#__PURE__*/React.createElement(Pill, {
    active: hashtagSort === 'avg_er',
    onClick: () => setHashtagSort('avg_er')
  }, "ER")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(5, minmax(140px, 1fr))',
      gap: 8
    }
  }, hashtagSorted.map((h, i) => /*#__PURE__*/React.createElement("div", {
    key: `${h.tag}-${i}`,
    style: {
      border: '1px solid var(--line)',
      borderRadius: 10,
      padding: '8px 10px',
      background: 'rgba(255,255,255,0.02)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      color: '#cbd5e1'
    }
  }, "#", h.tag), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginTop: 4
    }
  }, fmt(Number(h.count || 0)), " \u043F\u043E\u0441\u0442. \xB7 ", fmt(Number(h.avg_views || 0)), " \u043F\u0440\u043E\u0441\u043C."), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: '#4ade80',
      marginTop: 2
    }
  }, "ER ", Number(h.avg_er || 0).toFixed(2), "%")))), hashtagSorted.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-mute)'
    }
  }, "\u041D\u0435\u0442 \u0434\u0430\u043D\u043D\u044B\u0445 \u043F\u043E \u0445\u0435\u0448\u0442\u0435\u0433\u0430\u043C.")), /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      padding: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      marginBottom: 10,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u041B\u0443\u0447\u0448\u0435\u0435 \u0432\u0440\u0435\u043C\u044F \u0434\u043B\u044F \u043F\u043E\u0441\u0442\u0438\u043D\u0433\u0430"), /*#__PURE__*/React.createElement(InfoButton, {
    onClick: () => uiAlert('Этот блок показывает средние просмотры по часам и дням недели (МСК), чтобы выбрать лучшее время публикации.', 'Лучшее время для постинга'),
    title: "\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435: \u041B\u0443\u0447\u0448\u0435\u0435 \u0432\u0440\u0435\u043C\u044F \u0434\u043B\u044F \u043F\u043E\u0441\u0442\u0438\u043D\u0433\u0430",
    size: 11
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.14em',
      marginBottom: 8
    }
  }, "\u041F\u041E \u0427\u0410\u0421\u0410\u041C (\u041C\u0421\u041A)"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(12, 1fr)',
      gap: 6
    }
  }, bestHours.map(h => {
    const alpha = Math.max(0.12, Math.min(1, Number(h.avg_views || 0) / maxHourViews));
    return /*#__PURE__*/React.createElement("div", {
      key: `h-${h.hour}`,
      title: `${String(h.hour).padStart(2, '0')}:00 · ${fmt(Number(h.avg_views || 0))} avg views`,
      style: {
        height: 26,
        borderRadius: 6,
        border: '1px solid rgba(74,222,128,0.25)',
        background: `rgba(74,222,128,${(alpha * 0.45).toFixed(3)})`
      }
    });
  })), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      marginTop: 6,
      fontSize: 10,
      color: 'var(--ink-mute)'
    }
  }, "00:00 \xB7 06:00 \xB7 12:00 \xB7 18:00 \xB7 23:00")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.14em',
      marginBottom: 8
    }
  }, "\u041F\u041E \u0414\u041D\u042F\u041C \u041D\u0415\u0414\u0415\u041B\u0418"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, bestWeekdays.map(d => /*#__PURE__*/React.createElement("div", {
    key: `wd-${d.weekday}`,
    style: {
      display: 'grid',
      gridTemplateColumns: '54px 1fr auto',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-dim)'
    }
  }, d.weekday_label), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      borderRadius: 999,
      background: 'rgba(255,255,255,0.06)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${Math.max(0, Math.min(100, Number(d.avg_views || 0) / maxWeekdayViews * 100))}%`,
      height: '100%',
      background: 'linear-gradient(90deg, #6aa9ff, #4ade80)'
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, fmt(Number(d.avg_views || 0)))))))))) : null));
}
function PostRow({
  p,
  accent,
  rank,
  max,
  isMobile = false,
  onOpenAccount
}) {
  const meta = PLATFORM_META[p.platform] || {
    color: '#9ca3af',
    label: p.platform || 'Unknown'
  };
  const scrapeMissing = Boolean(p.scrapeNotFound);
  const w = scrapeMissing ? 0 : Math.max(0, p.delta / Math.max(1, max) * 100);
  const [thumbBroken, setThumbBroken] = React.useState(false);
  const username = String(p.username || p.handle || '').replace(/^@/, '');
  const postHref = scrapeMissing ? null : _postOpenUrl(p.platform, username, p.externalId, p.postUrl);
  React.useEffect(() => {
    setThumbBroken(false);
  }, [p.thumb]);
  return /*#__PURE__*/React.createElement("div", {
    role: postHref ? 'link' : undefined,
    tabIndex: postHref ? 0 : undefined,
    title: scrapeMissing ? 'Не найден при обновлении' : postHref ? 'Открыть публикацию на площадке' : undefined,
    onClick: () => {
      if (postHref) _openPostInNewTab(p.platform, username, p.externalId, p.postUrl);
    },
    onKeyDown: e => {
      if (!postHref) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        _openPostInNewTab(p.platform, username, p.externalId, p.postUrl);
      }
    },
    style: {
      position: 'relative',
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '40px 64px minmax(120px, 1fr) auto 82px',
      gap: isMobile ? 10 : 14,
      alignItems: 'center',
      padding: isMobile ? '12px 12px' : '14px 18px',
      borderRadius: 14,
      border: scrapeMissing ? '1px solid rgba(251,146,60,0.55)' : '1px solid var(--line)',
      background: scrapeMissing ? 'rgba(251,146,60,0.06)' : 'rgba(255,255,255,0.015)',
      overflow: 'hidden',
      cursor: postHref ? 'pointer' : 'default'
    }
  }, scrapeMissing ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    title: "\u041F\u0435\u0440\u0435\u0439\u0442\u0438 \u0432 \u043A\u0430\u0440\u0442\u043E\u0447\u043A\u0443 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430",
    "aria-label": "\u041F\u0443\u0431\u043B\u0438\u043A\u0430\u0446\u0438\u044F \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u0430 \u043F\u0440\u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438 \u2014 \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442",
    onClick: e => {
      e.preventDefault();
      e.stopPropagation();
      if (p.accountId && onOpenAccount) onOpenAccount(p.accountId);
    },
    style: {
      position: 'absolute',
      top: 6,
      right: 6,
      zIndex: 3,
      padding: 6,
      border: 'none',
      background: 'transparent',
      cursor: p.accountId && onOpenAccount ? 'pointer' : 'default',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(ScrapeMissingDot, null)) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      bottom: 0,
      left: 0,
      width: `${w}%`,
      background: `linear-gradient(90deg, ${meta.color}10, transparent)`,
      opacity: 0.8
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      position: 'relative',
      fontSize: isMobile ? 15 : 18,
      fontWeight: 700,
      color: rank <= 3 ? accent : 'var(--ink-mute)'
    }
  }, String(rank).padStart(2, '0')), !isMobile && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: 64,
      height: 64,
      borderRadius: 8,
      background: p.thumb && !thumbBroken ? '#0b1220' : `linear-gradient(135deg, ${meta.color}40, rgba(255,255,255,0.05))`,
      border: '1px solid var(--line)',
      overflow: 'hidden'
    }
  }, p.thumb && !thumbBroken ? /*#__PURE__*/React.createElement("img", {
    src: p.thumb,
    alt: "",
    onError: () => setThumbBroken(true),
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover',
      display: 'block'
    }
  }) : /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 8,
      color: 'var(--ink-mute)',
      letterSpacing: '0.1em'
    }
  }, "NO IMAGE")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 4,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: p.platform,
    size: 14
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 500,
      minWidth: 0,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, p.handle), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: scrapeMissing ? 'rgba(251,191,36,0.9)' : 'var(--ink-mute)',
      marginLeft: 'auto',
      flexShrink: 0
    }
  }, scrapeMissing && p.missingSince ? `с ${p.missingSince}` : p.date)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink-dim)',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, p.text)), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      display: 'flex',
      gap: 14,
      fontSize: 13,
      flexWrap: 'nowrap',
      justifyContent: isMobile ? 'flex-start' : 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      color: 'var(--ink-dim)',
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(EyeIcon, {
    size: 12,
    color: "currentColor"
  }), " ", fmt(p.views)), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      color: 'var(--ink-dim)'
    }
  }, "\u2665 ", fmt(p.likes)), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      color: 'var(--ink-mute)'
    }
  }, "ER ", p.er.toFixed(1), "%")), /*#__PURE__*/React.createElement("div", {
    className: "mono tnum",
    style: {
      position: 'relative',
      fontSize: isMobile ? 18 : 20,
      fontWeight: 600,
      color: scrapeMissing ? 'rgba(251,191,36,0.95)' : '#4ade80',
      textAlign: isMobile ? 'left' : 'right'
    }
  }, scrapeMissing ? 'не в съёме' : `+${fmt(p.delta)}`));
}
Object.assign(window, {
  AnalyticsScreen
});

// ===== screen-settings.jsx =====
// Settings (auth) screen — atomic-themed redesign of "Настройки авторизации".

function _authStartEndpoint(platformId) {
  return `/api/settings/${platformId}/start-auth/`;
}
function _authLogoutEndpoint(platformId) {
  return `/api/settings/${platformId}/logout/`;
}
function _authImportCookiesEndpoint(platformId) {
  const supported = new Set(['tiktok', 'instagram', 'x', 'threads', 'facebook', 'rumble', 'reddit']);
  if (!supported.has(platformId)) return null;
  return `/api/settings/${platformId}/import-cookies/`;
}

/** Ожидание фоновой задачи входа (POST …/start-auth/ → job_id). */
async function _pollAuthJob(jobId, {
  maxMs = 240000,
  intervalMs = 700
} = {}) {
  const deadline = Date.now() + maxMs;
  let lastMsg = '';
  while (Date.now() < deadline) {
    const st = await _fetchJson(`/api/settings/job/${encodeURIComponent(jobId)}/`);
    const msg = String(st?.message || '').trim();
    if (msg) lastMsg = msg;
    if (st?.status === 'done') return st;
    if (st?.status === 'error') {
      throw new Error(msg || 'Ошибка авторизации');
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error(lastMsg ? `${lastMsg}\n\nПревышено время ожидания. Проверьте панель задач — окно Chromium могло открыться за другими окнами.` : 'Превышено время ожидания. Проверьте, открылось ли окно браузера (панель задач).');
}
const BROWSER_PROFILE_PLATFORMS = {
  tiktok: {
    label: 'TikTok',
    apiPath: '/api/settings/tiktok/browser-profile/',
    hint: 'Два отдельных Chrome-профиля для обновления аккаунтов; вход и прогрев — всегда в профиле с авторизацией.'
  },
  facebook: {
    label: 'Facebook',
    apiPath: '/api/settings/facebook/browser-profile/',
    hint: 'Используются при входе, обновлении страниц и Reels. Для RU-аккаунтов оставьте locale ru-RU.'
  }
};

/** Параметры окна/движка, в котором открыт этот интерфейс (не Playwright). */
function _draftFromCurrentBrowserWindow() {
  const langs = typeof navigator !== 'undefined' && navigator.languages?.length ? [...navigator.languages].map(l => String(l).trim()).filter(Boolean) : [];
  const locale = typeof navigator !== 'undefined' && navigator.language ? String(navigator.language).trim() : 'en-US';
  const clamp = (n, lo, hi, fallback) => {
    const v = Math.round(Number(n) || fallback);
    return Math.max(lo, Math.min(hi, v));
  };
  return {
    user_agent: typeof navigator !== 'undefined' ? String(navigator.userAgent || '') : '',
    viewport_width: clamp(window.innerWidth, 320, 7680, 1280),
    viewport_height: clamp(window.innerHeight, 240, 4320, 900),
    locale: locale || 'en-US',
    languages: langs.length ? langs.join(', ') : locale || 'en-US'
  };
}
function PlatformBrowserProfileModal({
  platform,
  accent,
  onClose
}) {
  const meta = BROWSER_PROFILE_PLATFORMS[platform] || BROWSER_PROFILE_PLATFORMS.tiktok;
  const [loading, setLoading] = useStateMd(true);
  const [saving, setSaving] = useStateMd(false);
  const [draft, setDraft] = useStateMd(null);
  const [error, setError] = useStateMd('');
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const data = await _fetchJson(meta.apiPath);
        if (cancelled) return;
        const langs = Array.isArray(data?.languages) ? data.languages.join(', ') : String(data?.languages || '');
        setDraft({
          user_agent: String(data?.user_agent || ''),
          viewport_width: Number(data?.viewport_width) || 1280,
          viewport_height: Number(data?.viewport_height) || 900,
          locale: String(data?.locale || 'en-US'),
          languages: langs,
          stealth_enabled: data?.stealth_enabled !== false,
          hide_automation_flags: data?.hide_automation_flags !== false,
          refresh_browser_slot: String(data?.refresh_browser_slot || 'authorized'),
          browser_slots: Array.isArray(data?.browser_slots) ? data.browser_slots : []
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [platform]);
  const setField = (key, value) => setDraft(d => d ? {
    ...d,
    [key]: value
  } : d);
  const applyCurrentBrowserParams = () => {
    const cur = _draftFromCurrentBrowserWindow();
    setDraft(d => d ? {
      ...d,
      ...cur
    } : {
      ...cur,
      stealth_enabled: true,
      hide_automation_flags: true
    });
    setError('');
  };
  const save = async (resetDefaults = false) => {
    setSaving(true);
    setError('');
    try {
      const body = resetDefaults ? {
        reset_defaults: true
      } : {
        user_agent: draft?.user_agent,
        viewport_width: Number(draft?.viewport_width),
        viewport_height: Number(draft?.viewport_height),
        locale: draft?.locale,
        languages: draft?.languages,
        stealth_enabled: !!draft?.stealth_enabled,
        hide_automation_flags: !!draft?.hide_automation_flags,
        ...(platform === 'tiktok' ? {
          refresh_browser_slot: draft?.refresh_browser_slot || 'authorized'
        } : {})
      };
      const res = await _patchJson(meta.apiPath, body);
      await uiAlert(String(res?.message || 'Сохранено.'), 'Параметры браузера');
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };
  const inputStyle = {
    width: '100%',
    padding: '8px 10px',
    borderRadius: 8,
    border: '1px solid var(--line)',
    background: 'rgba(255,255,255,0.03)',
    color: 'var(--ink)',
    fontSize: 12,
    fontFamily: 'JetBrains Mono, monospace'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 110,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.72)',
      padding: 16
    },
    onClick: e => {
      if (e.target === e.currentTarget && !saving) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": true,
    "aria-labelledby": "platform-browser-profile-title",
    onClick: e => e.stopPropagation(),
    style: {
      width: '100%',
      maxWidth: 520,
      maxHeight: '90vh',
      overflow: 'auto',
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(18,20,28,0.98)',
      padding: 20,
      boxShadow: '0 24px 56px rgba(0,0,0,0.65)'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    id: "platform-browser-profile-title",
    style: {
      margin: '0 0 6px',
      fontSize: 17,
      color: '#fff'
    }
  }, "\u041F\u0430\u0440\u0430\u043C\u0435\u0442\u0440\u044B \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430 ", meta.label), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 10px',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, meta.hint, " \u041F\u043E\u0441\u043B\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0438\u044F \u0434\u0435\u043C\u043E\u043D ", meta.label, " \u043F\u0435\u0440\u0435\u0437\u0430\u043F\u0443\u0441\u043A\u0430\u0435\u0442\u0441\u044F."), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: saving || loading || !draft,
    onClick: applyCurrentBrowserParams,
    title: "User-Agent, \u0440\u0430\u0437\u043C\u0435\u0440 \u043E\u043A\u043D\u0430 \u0438 \u044F\u0437\u044B\u043A\u0438 \u0438\u0437 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430, \u0433\u0434\u0435 \u043E\u0442\u043A\u0440\u044B\u0442 \u0434\u0430\u0448\u0431\u043E\u0440\u0434",
    style: {
      width: '100%',
      marginBottom: 14,
      padding: '10px 14px',
      borderRadius: 10,
      border: `1px solid ${accent || '#6aa9ff'}55`,
      background: `${accent || '#6aa9ff'}18`,
      color: 'var(--ink)',
      fontSize: 13,
      fontWeight: 500,
      cursor: saving ? 'not-allowed' : 'pointer',
      opacity: saving ? 0.6 : 1
    }
  }, "\u0418\u0441\u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u044C \u0442\u0435\u043A\u0443\u0449\u0438\u0435 \u043F\u0430\u0440\u0430\u043C\u0435\u0442\u0440\u044B (\u044D\u0442\u043E\u0442 \u0431\u0440\u0430\u0443\u0437\u0435\u0440)"), loading && /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 13,
      marginBottom: 10
    }
  }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430\u2026"), error && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 12,
      padding: 10,
      borderRadius: 8,
      background: '#ef444418',
      border: '1px solid #ef444440',
      color: '#fca5a5',
      fontSize: 12
    }
  }, error), !loading && draft && platform === 'tiktok' && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14,
      padding: 12,
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.02)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: 'var(--ink)',
      marginBottom: 8
    }
  }, "\u0411\u0440\u0430\u0443\u0437\u0435\u0440 \u0434\u043B\u044F \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 10px',
      fontSize: 11,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, "\u0414\u0432\u0430 \u0440\u0430\u0437\u043D\u044B\u0445 \u043A\u0430\u0442\u0430\u043B\u043E\u0433\u0430 Chrome (\u043E\u0442\u0434\u0435\u043B\u044C\u043D\u044B\u0435 \u043E\u043A\u043D\u0430 \u0438 \u043A\u0443\u043A\u0438). \u0412\u0445\u043E\u0434 \u0432 TikTok \u0438 \u043F\u0440\u043E\u0433\u0440\u0435\u0432 \u0432\u0441\u0435\u0433\u0434\u0430 \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u044E\u0442 \u043F\u0440\u043E\u0444\u0438\u043B\u044C \u0441 \u0430\u0432\u0442\u043E\u0440\u0438\u0437\u0430\u0446\u0438\u0435\u0439."), (draft.browser_slots?.length ? draft.browser_slots : [{
    id: 'authorized',
    label: 'Chrome с авторизацией',
    hint: '',
    user_data_dir: '',
    state_exists: false
  }, {
    id: 'secondary',
    label: 'Отдельный Chrome без авторизации',
    hint: '',
    user_data_dir: '',
    state_exists: false
  }]).map(slot => /*#__PURE__*/React.createElement("label", {
    key: slot.id,
    style: {
      display: 'block',
      marginBottom: 8,
      padding: '10px 12px',
      borderRadius: 8,
      border: `1px solid ${draft.refresh_browser_slot === slot.id ? (accent || '#6aa9ff') + '88' : 'var(--line)'}`,
      background: draft.refresh_browser_slot === slot.id ? `${accent || '#6aa9ff'}12` : 'transparent',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "radio",
    name: "tiktok_refresh_browser_slot",
    checked: draft.refresh_browser_slot === slot.id,
    onChange: () => setField('refresh_browser_slot', slot.id),
    style: {
      marginTop: 3
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink)',
      fontWeight: 500
    }
  }, slot.label), slot.hint && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.4
    }
  }, slot.hint), slot.user_data_dir && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: 'var(--ink-dim)',
      marginTop: 4,
      fontFamily: 'JetBrains Mono, monospace',
      wordBreak: 'break-all'
    }
  }, slot.user_data_dir, slot.state_exists ? ' · cookies есть' : ' · без cookies')))))), !loading && draft && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "User-Agent", /*#__PURE__*/React.createElement("textarea", {
    value: draft.user_agent,
    onChange: e => setField('user_agent', e.target.value),
    rows: 3,
    style: {
      ...inputStyle,
      marginTop: 4,
      resize: 'vertical',
      minHeight: 64
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "\u0428\u0438\u0440\u0438\u043D\u0430 \u043E\u043A\u043D\u0430", /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: 320,
    max: 7680,
    value: draft.viewport_width,
    onChange: e => setField('viewport_width', e.target.value),
    style: {
      ...inputStyle,
      marginTop: 4
    }
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "\u0412\u044B\u0441\u043E\u0442\u0430 \u043E\u043A\u043D\u0430", /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: 240,
    max: 4320,
    value: draft.viewport_height,
    onChange: e => setField('viewport_height', e.target.value),
    style: {
      ...inputStyle,
      marginTop: 4
    }
  }))), /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "Locale (\u044F\u0437\u044B\u043A \u0438\u043D\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430 Playwright)", /*#__PURE__*/React.createElement("input", {
    type: "text",
    value: draft.locale,
    onChange: e => setField('locale', e.target.value),
    placeholder: "en-US",
    style: {
      ...inputStyle,
      marginTop: 4
    }
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "navigator.languages (\u0447\u0435\u0440\u0435\u0437 \u0437\u0430\u043F\u044F\u0442\u0443\u044E)", /*#__PURE__*/React.createElement("input", {
    type: "text",
    value: draft.languages,
    onChange: e => setField('languages', e.target.value),
    placeholder: "en-US, en",
    style: {
      ...inputStyle,
      marginTop: 4
    }
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 12,
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: draft.stealth_enabled,
    onChange: e => setField('stealth_enabled', e.target.checked)
  }), "\u041C\u0430\u0441\u043A\u0438\u0440\u043E\u0432\u043A\u0430 automation (webdriver, plugins, languages)"), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 12,
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: draft.hide_automation_flags,
    onChange: e => setField('hide_automation_flags', e.target.checked)
  }), "\u0424\u043B\u0430\u0433 --disable-blink-features=AutomationControlled")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      justifyContent: 'flex-end',
      alignItems: 'center',
      gap: 8,
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: saving || loading,
    onClick: () => save(true),
    style: {
      padding: '8px 12px',
      borderRadius: 8,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      fontSize: 12,
      cursor: 'pointer'
    }
  }, "\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u043F\u043E \u0443\u043C\u043E\u043B\u0447\u0430\u043D\u0438\u044E"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: saving,
    onClick: onClose,
    style: {
      padding: '8px 12px',
      borderRadius: 8,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      fontSize: 12,
      cursor: 'pointer'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: saving || loading || !draft,
    onClick: () => save(false),
    style: {
      padding: '8px 14px',
      borderRadius: 8,
      border: 'none',
      background: accent || '#6aa9ff',
      color: '#000',
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer',
      opacity: saving || loading ? 0.6 : 1
    }
  }, saving ? 'Сохранение…' : 'Сохранить'))));
}
function SettingsScreen({
  tweaks,
  onBack,
  onDataChanged,
  onOpenGlobalModal
}) {
  const isMobile = useIsMobile(980);
  const accent = tweaks.accent || '#6aa9ff';
  const [browserProfilePlatform, setBrowserProfilePlatform] = useStateMd(null);
  const fallbackPlatforms = [{
    id: 'tiktok',
    name: 'TikTok',
    state: 'active',
    expires: '5 дн.',
    meta: 'perf_feed_cache',
    warn: true,
    account: null
  }, {
    id: 'instagram',
    name: 'Instagram',
    state: 'active',
    updated: '2026-05-04 08:47 UTC',
    warn: false,
    account: '@asti22297'
  }, {
    id: 'telegram',
    name: 'Telegram',
    state: 'detected',
    meta: 'Данные хранятся в браузерном профиле',
    warn: false,
    account: null
  }, {
    id: 'youtube',
    name: 'YouTube',
    state: 'active',
    updated: '2026-05-06 14:12 UTC',
    warn: false,
    account: '@phil.studio'
  }, {
    id: 'x',
    name: 'X (Twitter)',
    state: 'expired',
    warn: true,
    account: null
  }, {
    id: 'threads',
    name: 'Threads',
    state: 'active',
    updated: '2026-05-05 10:24 UTC',
    warn: false,
    account: '@asti22297'
  }];
  const platforms = AUTH_SESSIONS.length > 0 ? AUTH_SESSIONS : fallbackPlatforms;
  const activeCount = platforms.filter(p => p.state === 'active' || p.state === 'detected').length;
  const expiringCount = platforms.filter(p => p.warn).length;
  const expiredCount = platforms.filter(p => p.state === 'expired').length;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh'
    },
    "data-screen-label": "Settings"
  }, /*#__PURE__*/React.createElement(TopBar, {
    accent: accent,
    onRefreshAll: () => onOpenGlobalModal?.('refresh_all'),
    onOpenSchedule: () => onOpenGlobalModal?.('schedule'),
    onOpenAddList: () => onOpenGlobalModal?.('add_list'),
    onOpenAddOne: () => onOpenGlobalModal?.('add_one')
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: isMobile ? '12px 10px 132px' : '28px 36px 80px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      marginBottom: isMobile ? 14 : 24,
      flexWrap: isMobile ? 'wrap' : 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onBack,
    style: {
      padding: '8px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--line)',
      color: 'var(--ink)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u2190 \u041D\u0430\u0437\u0430\u0434"), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.22em'
    }
  }, "SECURITY \xB7 SESSIONS"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: isMobile ? 22 : 26,
      fontWeight: 600,
      marginTop: 2,
      letterSpacing: '-0.01em'
    }
  }, "\u041D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438 \u0430\u0432\u0442\u043E\u0440\u0438\u0437\u0430\u0446\u0438\u0438"))), /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 14,
      lineHeight: 1.6,
      marginBottom: isMobile ? 12 : 16,
      maxWidth: 720
    }
  }, "\u0414\u043B\u044F \u0441\u0431\u043E\u0440\u0430 \u0434\u0430\u043D\u043D\u044B\u0445 \u043F\u0440\u0438\u043B\u043E\u0436\u0435\u043D\u0438\u0435 \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0435\u0442 \u0430\u0432\u0442\u043E\u0440\u0438\u0437\u043E\u0432\u0430\u043D\u043D\u044B\u0435 \u0441\u0435\u0441\u0441\u0438\u0438 \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435. \u041D\u0430\u0436\u043C\u0438\u0442\u0435 \u043A\u043D\u043E\u043F\u043A\u0443 \u2014 \u043E\u0442\u043A\u0440\u043E\u0435\u0442\u0441\u044F \u043E\u043A\u043D\u043E, \u0432\u043E\u0439\u0434\u0438\u0442\u0435 \u0432 \u0430\u043A\u043A\u0430\u0443\u043D\u0442, \u0438 \u0434\u0430\u043D\u043D\u044B\u0435 \u0431\u0443\u0434\u0443\u0442 \u043E\u0431\u043D\u043E\u0432\u043B\u044F\u0442\u044C\u0441\u044F \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u0435\u0441\u043A\u0438."), browserProfilePlatform && /*#__PURE__*/React.createElement(PlatformBrowserProfileModal, {
    platform: browserProfilePlatform,
    accent: accent,
    onClose: () => setBrowserProfilePlatform(null)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr 1fr 1fr' : '1fr 1fr 1fr',
      gap: isMobile ? 8 : 14,
      marginBottom: isMobile ? 16 : 28
    }
  }, /*#__PURE__*/React.createElement(SummaryTile, {
    label: "\u0410\u041A\u0422\u0418\u0412\u041D\u042B\u0425",
    value: String(activeCount),
    color: "#4ade80"
  }), /*#__PURE__*/React.createElement(SummaryTile, {
    label: "\u0418\u0421\u0422\u0415\u041A\u0410\u042E\u0422",
    value: String(expiringCount),
    color: "#f59e0b",
    warn: true
  }), /*#__PURE__*/React.createElement(SummaryTile, {
    label: "\u0418\u0421\u0422\u0415\u041A\u041B\u041E",
    value: String(expiredCount),
    color: "#ef4444"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
      gap: 14
    }
  }, platforms.map(p => /*#__PURE__*/React.createElement(SessionCard, {
    key: p.id,
    p: p,
    accent: accent,
    onDataChanged: onDataChanged,
    onOpenBrowserProfile: p.id === 'tiktok' || p.id === 'facebook' ? () => setBrowserProfilePlatform(p.id) : undefined
  })))));
}
function SummaryTile({
  label,
  value,
  color,
  warn
}) {
  const isMobile = useIsMobile(980);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: isMobile ? 14 : 20,
      borderRadius: 14,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      width: 4,
      bottom: 0,
      background: color,
      opacity: 0.6
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.22em'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    className: "tnum",
    style: {
      fontSize: isMobile ? 34 : 40,
      fontWeight: 700,
      color,
      marginTop: 4,
      letterSpacing: '-0.02em'
    }
  }, value));
}
function SessionCard({
  p,
  accent,
  onDataChanged,
  onOpenBrowserProfile
}) {
  const isMobile = useIsMobile(980);
  const meta = PLATFORM_META[p.id];
  const stateColor = p.state === 'active' || p.state === 'detected' ? '#4ade80' : p.state === 'expired' ? '#ef4444' : '#f59e0b';
  const stateLabel = p.state === 'active' ? 'Авторизован' : p.state === 'detected' ? 'Обнаружено' : 'Истекло';
  const stateLabelMobile = p.state === 'active' ? 'Акт.' : p.state === 'detected' ? 'Найд.' : 'Истек';
  const [busy, setBusy] = useStateMd(false);
  const [showImport, setShowImport] = useStateMd(false);
  const [cookiesRaw, setCookiesRaw] = useStateMd('');
  const [importBusy, setImportBusy] = useStateMd(false);
  const importEndpoint = _authImportCookiesEndpoint(p.id);
  const doAuth = async () => {
    setBusy(true);
    try {
      const res = await _postJson(_authStartEndpoint(p.id), {});
      const jobId = res?.job_id;
      if (!jobId) {
        throw new Error('Сервер не вернул идентификатор задачи (job_id).');
      }
      const st = await _pollAuthJob(jobId);
      await uiAlert(String(st?.message || 'Авторизация завершена.'), 'Авторизация');
      await onDataChanged?.();
    } catch (e) {
      await uiAlert(`Не удалось выполнить авторизацию: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setBusy(false);
    }
  };
  const doLogout = async () => {
    setBusy(true);
    try {
      await _postJson(_authLogoutEndpoint(p.id), {});
      await onDataChanged?.();
    } catch (e) {
      await uiAlert(`Не удалось завершить сессию: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setBusy(false);
    }
  };
  const doImportCookies = async () => {
    if (!importEndpoint) return;
    if (!cookiesRaw.trim()) {
      await uiAlert('Вставь JSON cookies.', 'Импорт cookies');
      return;
    }
    setImportBusy(true);
    try {
      const res = await _postJson(importEndpoint, {
        cookies: cookiesRaw.trim()
      });
      const jobId = res?.job_id;
      if (!jobId) {
        throw new Error('Сервер не вернул идентификатор задачи (job_id).');
      }
      const st = await _pollAuthJob(jobId, {
        maxMs: 120000
      });
      setShowImport(false);
      setCookiesRaw('');
      await onDataChanged?.();
      await uiAlert(String(st?.message || 'Cookies импортированы.'), 'Импорт cookies');
    } catch (e) {
      await uiAlert(`Не удалось импортировать cookies: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setImportBusy(false);
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: isMobile ? 14 : 22,
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.015)',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 1,
      background: `linear-gradient(90deg, transparent, ${meta?.color || accent}, transparent)`,
      opacity: 0.5
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 12,
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: isMobile ? 32 : 36,
      height: isMobile ? 32 : 36,
      borderRadius: 10,
      background: 'rgba(255,255,255,0.04)',
      border: `1px solid ${meta?.color}40`,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: meta?.color,
      fontWeight: 700,
      fontFamily: 'JetBrains Mono, monospace'
    }
  }, p.name.charAt(0)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: isMobile ? 24 : 18,
      fontWeight: 600
    }
  }, p.name)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      flexShrink: 0,
      padding: isMobile ? '4px 8px' : '3px 8px',
      borderRadius: 999,
      background: `${stateColor}1f`,
      border: `1px solid ${stateColor}4d`
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: 999,
      background: stateColor,
      boxShadow: `0 0 8px ${stateColor}`
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: isMobile ? 10 : 11,
      color: stateColor,
      letterSpacing: isMobile ? '0.06em' : '0.14em',
      textTransform: 'uppercase'
    }
  }, isMobile ? stateLabelMobile : stateLabel))), p.account && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: isMobile ? 12 : 13,
      color: 'var(--ink-dim)',
      marginBottom: 4
    }
  }, p.account), p.updated && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: isMobile ? 11 : 12,
      color: 'var(--ink-mute)'
    }
  }, "\u041E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u043E: ", p.updated), p.expires && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      padding: '6px 10px',
      display: 'inline-flex',
      gap: 8,
      alignItems: 'center',
      borderRadius: 8,
      background: '#ef444415',
      border: '1px solid #ef444433',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: '#ef4444'
    }
  }, "\u25CF ", p.expires), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, p.meta)), p.meta && !p.expires && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: isMobile ? 11 : 12,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.35
    }
  }, p.meta), p.warn && p.state === 'active' && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14,
      padding: '10px 12px',
      borderRadius: 10,
      background: '#f59e0b15',
      border: '1px solid #f59e0b40',
      display: 'flex',
      gap: 8,
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#f59e0b'
    }
  }, "\u26A0"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: isMobile ? 11 : 12,
      color: '#fbbf24',
      lineHeight: 1.35
    }
  }, "Cookies \u0441\u043A\u043E\u0440\u043E \u0438\u0441\u0442\u0435\u043A\u0443\u0442 \u2014 \u043E\u0431\u043D\u043E\u0432\u0438\u0442\u0435 \u0430\u0432\u0442\u043E\u0440\u0438\u0437\u0430\u0446\u0438\u044E.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: isMobile ? 'column' : 'row',
      gap: 10,
      marginTop: 16,
      alignItems: isMobile ? 'stretch' : 'center'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: doAuth,
    disabled: busy,
    style: {
      width: isMobile ? '100%' : 'auto',
      minHeight: isMobile ? 42 : undefined,
      padding: '8px 14px',
      borderRadius: 10,
      background: '#fff',
      color: '#000',
      border: 'none',
      fontSize: 13,
      fontWeight: 500,
      cursor: 'pointer',
      opacity: busy ? 0.6 : 1
    }
  }, busy ? '...' : p.hasSession ? 'Обновить авторизацию' : `Войти в ${p.name}`), p.hasSession && /*#__PURE__*/React.createElement("button", {
    onClick: doLogout,
    disabled: busy,
    style: {
      width: isMobile ? '100%' : 'auto',
      minHeight: isMobile ? 42 : undefined,
      padding: '8px 14px',
      borderRadius: 10,
      background: 'transparent',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit',
      opacity: busy ? 0.6 : 1
    }
  }, "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044C \u0441\u0435\u0441\u0441\u0438\u044E"), importEndpoint && /*#__PURE__*/React.createElement("button", {
    onClick: () => setShowImport(v => !v),
    style: {
      width: isMobile ? '100%' : 'auto',
      minHeight: isMobile ? 42 : undefined,
      padding: '8px 14px',
      borderRadius: 10,
      background: 'transparent',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u0418\u043C\u043F\u043E\u0440\u0442 cookies"), onOpenBrowserProfile && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onOpenBrowserProfile,
    style: {
      width: isMobile ? '100%' : 'auto',
      minHeight: isMobile ? 42 : undefined,
      padding: '8px 14px',
      borderRadius: 10,
      background: 'transparent',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u041F\u0430\u0440\u0430\u043C\u0435\u0442\u0440\u044B \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430")), showImport && importEndpoint && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      border: '1px solid var(--line)',
      borderRadius: 10,
      padding: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginBottom: 6
    }
  }, p.id === 'tiktok' ? 'Куки для Playwright-воркера (отдельный Chrome)' : `JSON cookies для ${p.name}`), p.id === 'tiktok' && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 8px',
      fontSize: 11,
      color: 'var(--ink-dim)',
      lineHeight: 1.45
    }
  }, "\u041E\u043A\u043D\u043E \u0432\u043E\u0440\u043A\u0435\u0440\u0430 \u2260 \u0432\u0430\u0448 \u0431\u0440\u0430\u0443\u0437\u0435\u0440. \u041F\u043E\u0441\u043B\u0435 \xAB\u0418\u043C\u043F\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C\xBB \u0434\u043E\u0436\u0434\u0438\u0442\u0435\u0441\u044C \xAB\u0413\u043E\u0442\u043E\u0432\u043E\xBB, \u0437\u0430\u0442\u0435\u043C \u0441\u043D\u043E\u0432\u0430 \u043E\u0442\u043A\u0440\u043E\u0439\u0442\u0435 \u0441\u044A\u0451\u043C. \u041B\u0443\u0447\u0448\u0435 \u0432\u0441\u0442\u0430\u0432\u0438\u0442\u044C ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: 'var(--ink)'
    }
  }, "JSON \u0432\u0441\u0435\u0445 \u043A\u0443\u043A\u043E\u0432"), " .tiktok.com (\u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043D\u0438\u0435 Cookie-Editor \u2192 Export). \u041E\u0434\u043D\u043E\u0433\u043E sessionid \u0438\u0437 DevTools \u0447\u0430\u0441\u0442\u043E \u043C\u0430\u043B\u043E; \u0442\u043E\u0442 \u0436\u0435 VPN, \u0447\u0442\u043E \u043F\u0440\u0438 \u0432\u0445\u043E\u0434\u0435. \xAB\u0421\u043B\u0438\u0448\u043A\u043E\u043C \u043C\u043D\u043E\u0433\u043E \u043F\u043E\u043F\u044B\u0442\u043E\u043A\xBB \u2014 \u043F\u0430\u0443\u0437\u0430 12\u201324 \u0447."), /*#__PURE__*/React.createElement("textarea", {
    value: cookiesRaw,
    onChange: e => setCookiesRaw(e.target.value),
    placeholder: p.id === 'tiktok' ? '[{"domain":".tiktok.com","name":"sessionid","value":"..."}, … все куки tiktok.com]' : '[{"domain":".example.com","name":"sessionid","value":"..."}]',
    style: {
      width: '100%',
      minHeight: 100,
      resize: 'vertical',
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid var(--line)',
      borderRadius: 8,
      color: 'var(--ink)',
      fontSize: 12,
      fontFamily: 'JetBrains Mono, monospace',
      padding: 8
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 8,
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setShowImport(false),
    style: {
      padding: '7px 12px',
      borderRadius: 8,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      fontSize: 12,
      cursor: 'pointer'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: doImportCookies,
    disabled: importBusy,
    style: {
      padding: '7px 12px',
      borderRadius: 8,
      border: 'none',
      background: '#fff',
      color: '#000',
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer',
      opacity: importBusy ? 0.6 : 1
    }
  }, importBusy ? 'Импорт...' : 'Импортировать'))));
}
Object.assign(window, {
  SettingsScreen
});

// ===== screen-modals.jsx =====
// Modal screens — Add list, Schedule, Add account form.

const {
  useState: useStateMd
} = React;
function ModalsScreen({
  tweaks,
  onDataChanged,
  initialTab
}) {
  const accent = tweaks.accent || '#6aa9ff';
  const [active, setActive] = useStateMd(initialTab || 'add_list');
  useEffect(() => {
    if (initialTab) setActive(initialTab);
  }, [initialTab]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      position: 'relative'
    },
    "data-screen-label": "Modals"
  }, /*#__PURE__*/React.createElement(TopBar, {
    accent: accent
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      padding: '28px 36px 60px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginBottom: 22
    }
  }, [['add_list', 'Добавить список'], ['schedule', 'Расписание'], ['add_one', 'Добавить аккаунт']].map(([id, l]) => /*#__PURE__*/React.createElement(Pill, {
    key: id,
    active: active === id,
    onClick: () => setActive(id)
  }, l))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      padding: 40
    }
  }, active === 'add_list' && /*#__PURE__*/React.createElement(AddListModal, {
    accent: accent,
    onDataChanged: onDataChanged
  }), active === 'schedule' && /*#__PURE__*/React.createElement(ScheduleModal, {
    accent: accent,
    onDataChanged: onDataChanged
  }), active === 'add_one' && /*#__PURE__*/React.createElement(AddOneInline, {
    accent: accent,
    onDataChanged: onDataChanged
  }))));
}
function ModalOverlay({
  children,
  onClose
}) {
  const isMobile = useIsMobile(760);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 120,
      display: 'grid',
      placeItems: 'center',
      padding: isMobile ? 8 : 18
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      position: 'absolute',
      inset: 0,
      border: 'none',
      background: 'rgba(0,0,0,0.78)',
      backdropFilter: 'blur(3px)',
      cursor: 'pointer'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 1
    }
  }, children));
}
function ModalShell({
  title,
  kicker,
  children,
  accent,
  width = 620,
  onClose,
  offsetY = '0%'
}) {
  const isMobile = useIsMobile(760);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: `min(${width}px, ${isMobile ? '96vw' : '92vw'})`,
      padding: isMobile ? 14 : 24,
      borderRadius: isMobile ? 14 : 22,
      background: 'linear-gradient(180deg, rgba(18,22,32,0.96), rgba(12,16,24,0.94))',
      border: '1px solid rgba(106,169,255,0.22)',
      position: 'relative',
      overflow: 'hidden',
      boxShadow: '0 24px 60px rgba(0,0,0,0.55)',
      maxHeight: isMobile ? '92vh' : '88vh',
      overflowY: 'auto',
      transform: !isMobile && offsetY !== '0%' ? `translateY(${offsetY})` : undefined
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 1,
      background: `linear-gradient(90deg, transparent, ${accent}, transparent)`
    }
  }), /*#__PURE__*/React.createElement(ParticleField, {
    count: 20,
    color: accent,
    opacity: 0.3
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: 22
    }
  }, /*#__PURE__*/React.createElement("div", null, kicker && /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      letterSpacing: '0.24em'
    }
  }, kicker), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 600,
      marginTop: 4,
      letterSpacing: '-0.01em'
    }
  }, title)), /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      width: 32,
      height: 32,
      borderRadius: 999,
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u2715")), children));
}
const PROFILE_PRESET_COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#64748b'];
function ProfileColorPicker({
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap',
      alignItems: 'center'
    }
  }, PROFILE_PRESET_COLORS.map(color => /*#__PURE__*/React.createElement("button", {
    key: color,
    type: "button",
    onClick: () => onChange?.(color),
    style: {
      width: 24,
      height: 24,
      borderRadius: 999,
      border: `2px solid ${value === color ? '#ffffff' : 'transparent'}`,
      background: color,
      cursor: 'pointer',
      transform: value === color ? 'scale(1.08)' : 'scale(1)',
      transition: 'transform .12s ease'
    }
  })));
}
function ProfileEditorModal({
  accent,
  mode,
  initialName = '',
  initialColor = '#6366f1',
  busy = false,
  onSubmit,
  onClose
}) {
  const [name, setName] = useStateMd(initialName);
  const [color, setColor] = useStateMd(initialColor || '#6366f1');
  const title = mode === 'edit' ? 'Редактировать профиль' : 'Новый профиль';
  const kicker = mode === 'edit' ? 'PROFILE EDIT' : 'PROFILE CREATE';
  const submitLabel = busy ? 'Сохраняю...' : mode === 'edit' ? 'Сохранить' : 'Создать';
  return /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: onClose
  }, /*#__PURE__*/React.createElement(ModalShell, {
    title: title,
    kicker: kicker,
    accent: accent,
    width: 560,
    onClose: onClose
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "\u041D\u0410\u0417\u0412\u0410\u041D\u0418\u0415"), /*#__PURE__*/React.createElement("input", {
    value: name,
    onChange: e => setName(e.target.value),
    placeholder: "\u041D\u0430\u0437\u0432\u0430\u043D\u0438\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u044F",
    autoFocus: true,
    style: {
      width: '100%',
      padding: '12px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink)',
      fontSize: 14,
      fontFamily: 'inherit'
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "\u0426\u0412\u0415\u0422"), /*#__PURE__*/React.createElement(ProfileColorPicker, {
    value: color,
    onChange: setColor
  }), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginTop: 10,
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "color",
    value: /^#[0-9a-fA-F]{6}$/.test(String(color || '')) ? color : '#6366f1',
    onChange: e => setColor(e.target.value),
    style: {
      width: 44,
      height: 32,
      padding: 2,
      border: '1px solid var(--line-2)',
      borderRadius: 8,
      background: 'transparent',
      cursor: 'pointer'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: 'var(--ink-dim)'
    }
  }, "\u0421\u0432\u043E\u0439 \u043E\u0442\u0442\u0435\u043D\u043E\u043A"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: 24
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      padding: '8px 0',
      background: 'transparent',
      border: 'none',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: () => onSubmit?.({
      name: String(name || '').trim(),
      color
    }),
    disabled: busy || !String(name || '').trim(),
    style: {
      padding: '12px 28px',
      borderRadius: 12,
      background: accent,
      color: '#000',
      border: 'none',
      fontSize: 14,
      fontWeight: 600,
      cursor: busy ? 'default' : 'pointer',
      opacity: busy || !String(name || '').trim() ? 0.6 : 1
    }
  }, submitLabel))));
}
function AddListModal({
  accent,
  onDataChanged,
  onClose
}) {
  const isMobile = useIsMobile(760);
  const [raw, setRaw] = useStateMd('');
  const [busy, setBusy] = useStateMd(false);
  const [importReport, setImportReport] = useStateMd(null);
  const [profileId, setProfileId] = useStateMd('none');
  const [profileBusy, setProfileBusy] = useStateMd(false);
  const [profileEditorOpen, setProfileEditorOpen] = useStateMd(false);
  const createProfileInline = async ({
    name,
    color
  }) => {
    const profileName = String(name || '').trim();
    if (!profileName) return;
    setProfileBusy(true);
    try {
      const created = await _postJson('/api/accounts/profiles/', {
        name: profileName,
        color: color || '#6366f1'
      });
      const createdId = created?.id != null ? String(created.id) : null;
      await onDataChanged?.();
      if (createdId) setProfileId(createdId);
      await uiAlert(`Профиль "${profileName}" добавлен.`, 'Профили');
      setProfileEditorOpen(false);
    } catch (e) {
      await uiAlert(`Не удалось добавить профиль: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setProfileBusy(false);
    }
  };
  const importBulk = async () => {
    const lines = raw.split(/\r?\n|,/).map(s => s.trim()).filter(Boolean);
    if (lines.length === 0) return;
    setBusy(true);
    setImportReport(null);
    let created = 0;
    let updated = 0;
    let unchanged = 0;
    const failed = [];
    const skipped = [];
    try {
      for (const line of lines) {
        const parsed = _parseBulkLine(line);
        if (!parsed || !parsed.username) {
          skipped.push({
            line,
            label: line,
            reason: 'Не удалось разобрать URL или username'
          });
          continue;
        }
        try {
          const {
            action
          } = await _importAccountFromBulkLine(parsed, profileId);
          if (action === 'created') created += 1;
          else if (action === 'profile_updated') updated += 1;
          else unchanged += 1;
        } catch (e) {
          failed.push({
            line,
            label: _bulkImportEntryLabel(parsed, line),
            reason: _friendlyBulkImportError(e instanceof Error ? e.message : String(e))
          });
        }
      }
      const touched = created + updated + unchanged;
      if (touched > 0) {
        await onDataChanged?.();
      }
      if (failed.length > 0) {
        setImportReport({
          created,
          updated,
          unchanged,
          failed,
          skipped
        });
      } else if (touched > 0) {
        const parts = [];
        if (created) parts.push(`добавлено: ${created}`);
        if (updated) parts.push(`профиль обновлён: ${updated}`);
        if (unchanged) parts.push(`без изменений: ${unchanged}`);
        if (skipped.length) parts.push(`не распознано: ${skipped.length}`);
        await uiAlert(parts.join('. ') + '.', 'Импорт списка');
        setRaw('');
      } else if (skipped.length > 0) {
        await uiAlert('Ни одна строка не распознана. Проверьте формат URL.', 'Импорт списка');
      } else {
        await uiAlert('Нечего импортировать.', 'Импорт списка');
      }
    } finally {
      setBusy(false);
    }
  };
  return /*#__PURE__*/React.createElement(ModalShell, {
    title: "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0441\u043F\u0438\u0441\u043E\u043A \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432",
    kicker: "BATCH IMPORT",
    accent: accent,
    width: 760,
    offsetY: "-10%",
    onClose: onClose
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink-dim)',
      marginBottom: 12
    }
  }, "\u0412\u0441\u0442\u0430\u0432\u044C URL \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432 \u2014 \u043F\u043E \u043E\u0434\u043D\u043E\u043C\u0443 \u043D\u0430 \u0441\u0442\u0440\u043E\u043A\u0443 \u0438\u043B\u0438 \u0447\u0435\u0440\u0435\u0437 \u0437\u0430\u043F\u044F\u0442\u0443\u044E"), /*#__PURE__*/React.createElement("textarea", {
    value: raw,
    onChange: e => setRaw(e.target.value),
    placeholder: 'https://www.tiktok.com/@username\nhttps://www.youtube.com/@channel\nhttps://www.threads.com/@user\nhttps://t.me/channel',
    style: {
      width: '100%',
      minHeight: 160,
      padding: 16,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink-dim)',
      fontSize: 13,
      fontFamily: 'JetBrains Mono, monospace',
      lineHeight: 1.6,
      resize: 'vertical'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      marginTop: 18,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em'
    }
  }, "\u041F\u0420\u041E\u0424\u0418\u041B\u042C"), /*#__PURE__*/React.createElement(ProfilePicker, {
    accent: accent,
    value: profileId,
    onChange: setProfileId
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => setProfileEditorOpen(true),
    disabled: profileBusy,
    style: {
      padding: '8px 14px',
      borderRadius: 999,
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      cursor: profileBusy ? 'default' : 'pointer',
      fontSize: 13,
      fontFamily: 'inherit',
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      opacity: profileBusy ? 0.7 : 1
    }
  }, profileBusy ? '...' : '+ Новый')), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: 28,
      gap: 10,
      flexWrap: isMobile ? 'wrap' : 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      padding: '8px 0',
      background: 'transparent',
      border: 'none',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: importBulk,
    disabled: busy,
    style: {
      padding: '12px 28px',
      borderRadius: 12,
      background: accent,
      color: '#000',
      border: 'none',
      fontSize: 14,
      fontWeight: 600,
      cursor: 'pointer',
      opacity: busy ? 0.6 : 1,
      width: isMobile ? '100%' : 'auto'
    }
  }, busy ? 'Импорт...' : 'Импортировать')), importReport && /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: () => setImportReport(null)
  }, /*#__PURE__*/React.createElement(ModalShell, {
    title: "Не все аккаунты добавлены",
    kicker: "IMPORT",
    accent: accent,
    width: 640,
    onClose: () => setImportReport(null)
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 14px',
      fontSize: 14,
      color: 'var(--ink-dim)',
      lineHeight: 1.5
    }
  }, (() => {
    const p = [];
    if (importReport.created) p.push(`добавлено: ${importReport.created}`);
    if (importReport.updated) p.push(`профиль обновлён: ${importReport.updated}`);
    if (importReport.unchanged) p.push(`без изменений: ${importReport.unchanged}`);
    if (importReport.failed?.length) p.push(`ошибки: ${importReport.failed.length}`);
    return p.length ? p.join('. ') + '.' : '';
  })()), /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 320,
      overflowY: 'auto',
      borderRadius: 12,
      border: '1px solid var(--line)',
      background: 'rgba(0,0,0,0.2)'
    }
  }, importReport.failed.map((item, idx) => /*#__PURE__*/React.createElement("div", {
    key: `${item.label}-${idx}`,
    style: {
      padding: '10px 14px',
      borderBottom: idx < importReport.failed.length - 1 ? '1px solid var(--line)' : 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 13,
      color: 'var(--ink)',
      marginBottom: 4,
      wordBreak: 'break-all'
    }
  }, item.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#f87171',
      lineHeight: 1.45
    }
  }, item.reason)))), importReport.skipped?.length > 0 && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '12px 0 0',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, `Не распознано строк: ${importReport.skipped.length}.`), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      setImportReport(null);
      if ((importReport.created || 0) + (importReport.updated || 0) + (importReport.unchanged || 0) > 0) setRaw('');
    },
    style: {
      padding: '10px 22px',
      borderRadius: 10,
      background: accent,
      color: '#000',
      border: 'none',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, "Понятно")))), profileEditorOpen && /*#__PURE__*/React.createElement(ProfileEditorModal, {
    accent: accent,
    mode: "create",
    busy: profileBusy,
    onSubmit: createProfileInline,
    onClose: () => {
      if (!profileBusy) setProfileEditorOpen(false);
    }
  }));
}
const _AUTO_RUN_STATUS_RU = {
  queued: 'В очереди',
  running: 'Обновляется',
  done: 'Готово',
  skipped: 'Пропущен',
  error: 'Ошибка',
  cancelled: 'Отменён'
};
const _WARM_STATUS_RU = {
  queued: 'В очереди',
  running: 'Прогрев',
  done: 'Готово',
  error: 'Ошибка',
  cancelled: 'Остановлен'
};
const _WARM_PLATFORM_ORDER = ['facebook'];
function AutoRefreshRunDetailOverlay({
  status,
  accent,
  onClose,
  refreshAutoStatus
}) {
  React.useEffect(() => {
    const t = setInterval(() => {
      void refreshAutoStatus?.();
    }, 6000);
    return () => clearInterval(t);
  }, [refreshAutoStatus]);
  const pipeline = status?.active_pipeline || '';
  const overlayKicker = pipeline === 'refresh_all' ? 'СБОР ВСЕХ' : pipeline === 'bulk_refresh' ? 'ВЫБРАННЫЕ' : 'АВТООБНОВЛЕНИЕ';
  const overlayTitle = pipeline === 'refresh_all' ? 'Детали сбора всех' : pipeline === 'bulk_refresh' ? 'Детали обновления выбранных' : 'Детали прогона';
  const rd = status?.run_detail && typeof status.run_detail === 'object' ? status.run_detail : {};
  const items = Array.isArray(rd.items) ? rd.items : [];
  const wc = Number(rd.worker_count || 0);
  const warmMap = rd.warm && typeof rd.warm === 'object' ? rd.warm : {};
  const warmRows = _WARM_PLATFORM_ORDER.filter(p => warmMap[p]).map(p => ({
    platform: p,
    ...warmMap[p]
  }));
  const fmtWarmTime = sec => {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, '0')}`;
  };
  const pick = s => items.filter(it => it.status === s);
  const buckets = {
    running: pick('running'),
    queued: pick('queued'),
    done: pick('done'),
    skipped: pick('skipped'),
    error: pick('error'),
    cancelled: pick('cancelled')
  };
  const warmSection = warmRows.length > 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.12em',
      marginBottom: 8
    }
  }, "\u041F\u0420\u041E\u0413\u0420\u0415\u0412 \xB7 ", warmRows.length), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, warmRows.map(w => {
    const pct = Math.max(0, Math.min(100, Number(w.progress_percent || 0)));
    const st = w.status || 'queued';
    const isRun = st === 'running';
    const planned = Number(w.planned_sec || 0);
    const elapsed = Number(w.elapsed_sec || 0);
    const minM = Number(w.min_minutes || 0);
    const maxM = Number(w.max_minutes || 0);
    const planLabel = minM > 0 && maxM > 0 ? `план ~${minM.toFixed(0)}–${maxM.toFixed(0)} мин` : planned > 0 ? `план ~${Math.ceil(planned / 60)} мин` : '';
    return /*#__PURE__*/React.createElement("div", {
      key: w.platform,
      style: {
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid var(--line)',
        background: isRun ? 'rgba(56,189,248,0.08)' : 'rgba(255,255,255,0.03)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement(PlatformGlyph, {
      id: w.platform,
      size: 14
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        fontSize: 13,
        fontWeight: 500,
        color: 'var(--ink)'
      }
    }, PLATFORM_META[w.platform]?.label || w.platform, w.detail ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--ink-mute)',
        fontWeight: 400
      }
    }, " \xB7 ", w.detail) : null), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        fontWeight: 600,
        padding: '3px 8px',
        borderRadius: 6,
        border: '1px solid var(--line)',
        background: isRun ? 'rgba(56,189,248,0.12)' : st === 'done' ? 'rgba(74,222,128,0.12)' : 'rgba(255,255,255,0.04)'
      }
    }, _WARM_STATUS_RU[st] || st)), (isRun || st === 'done') && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      style: {
        height: 8,
        borderRadius: 999,
        border: '1px solid var(--line)',
        background: 'rgba(255,255,255,0.04)',
        overflow: 'hidden',
        marginBottom: 6
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${pct}%`,
        height: '100%',
        borderRadius: 999,
        background: st === 'done' ? 'linear-gradient(90deg, #22c55e, #4ade80)' : 'linear-gradient(90deg, #38bdf8, #4ade80)',
        transition: 'width 260ms ease'
      }
    })), /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        fontSize: 11,
        color: 'var(--ink-mute)',
        display: 'flex',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", null, pct, "%", planned > 0 ? ` · ${fmtWarmTime(elapsed)} / ${fmtWarmTime(planned)}` : elapsed > 0 ? ` · ${fmtWarmTime(elapsed)}` : ''), /*#__PURE__*/React.createElement("span", null, "\u0440\u043E\u043B\u0438\u043A\u043E\u0432 ", Number(w.videos || 0), " \xB7 \u043B\u0430\u0439\u043A\u043E\u0432 ", Number(w.likes || 0))), planLabel ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        color: 'var(--ink-mute)',
        marginTop: 4
      }
    }, planLabel) : null), st === 'queued' && planLabel ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: 'var(--ink-mute)'
      }
    }, planLabel, " \u2014 \u0441\u043A\u043E\u0440\u043E \u0441\u0442\u0430\u0440\u0442") : null, st === 'error' && w.detail ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: '#fecaca',
        marginTop: 6,
        lineHeight: 1.35
      }
    }, w.detail) : null);
  }))) : null;
  const section = (title, list, emptyHint) => /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.12em',
      marginBottom: 8
    }
  }, title, " \xB7 ", list.length), list.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)'
    }
  }, emptyHint || '—') : /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 160,
      overflowY: 'auto',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(0,0,0,0.2)'
    }
  }, list.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.account_id,
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 8,
      padding: '8px 10px',
      borderBottom: '1px solid rgba(255,255,255,0.06)'
    }
  }, /*#__PURE__*/React.createElement(PlatformGlyph, {
    id: it.platform,
    size: 14
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--ink)',
      fontWeight: 500
    }
  }, "@", it.username, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-mute)',
      fontWeight: 400
    }
  }, "\xB7 ", it.platform)), it.detail ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.35
    }
  }, it.detail) : null), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      fontWeight: 600,
      padding: '3px 8px',
      borderRadius: 6,
      border: '1px solid var(--line)',
      background: it.status === 'running' ? 'rgba(56,189,248,0.12)' : it.status === 'done' ? 'rgba(74,222,128,0.12)' : 'rgba(255,255,255,0.04)',
      color: 'var(--ink)'
    }
  }, _AUTO_RUN_STATUS_RU[it.status] || it.status), it.worker != null && it.status === 'running' ? /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      marginTop: 4
    }
  }, "\u0441\u043B\u043E\u0442 ", Number(it.worker) + 1) : null)))));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 80,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.72)',
      padding: 16
    },
    onClick: e => e.target === e.currentTarget && onClose()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      maxWidth: 520,
      maxHeight: 'min(88vh, 620px)',
      overflowY: 'auto',
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(18,20,28,0.98)',
      padding: 20
    },
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 12,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 6
    }
  }, overlayKicker), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 17,
      fontWeight: 600,
      color: '#fff'
    }
  }, overlayTitle), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      marginTop: 8,
      lineHeight: 1.45
    }
  }, "\u041F\u0430\u0440\u0430\u043B\u043B\u0435\u043B\u044C\u043D\u044B\u0445 \u043F\u043E\u0442\u043E\u043A\u043E\u0432: ", wc || '—', ". \u041D\u043E\u043C\u0435\u0440 \u0441\u043B\u043E\u0442\u0430 1\u2026N \u2014 \u0442\u043E\u043B\u044C\u043A\u043E \u0443 \u0441\u0442\u0440\u043E\u043A\u0438 \xAB\u041E\u0431\u043D\u043E\u0432\u043B\u044F\u0435\u0442\u0441\u044F\xBB.")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, "\u2715")), warmSection, items.length === 0 && warmRows.length === 0 ? /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 13,
      color: 'var(--ink-mute)'
    }
  }, "\u0421\u043F\u0438\u0441\u043E\u043A \u0435\u0449\u0451 \u043D\u0435 \u043F\u0440\u0438\u0448\u0451\u043B \u0441 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 (\u043D\u0443\u0436\u043D\u0430 \u043C\u0438\u0433\u0440\u0430\u0446\u0438\u044F 0023 \u0438 \u043E\u0431\u043D\u043E\u0432\u043B\u0451\u043D\u043D\u044B\u0439 \u0431\u044D\u043A\u0435\u043D\u0434).") : /*#__PURE__*/React.createElement(React.Fragment, null, section('Сейчас обновляются', buckets.running, 'Никто'), section('В очереди', buckets.queued, 'Пусто'), section('Уже готово', buckets.done, '—'), section('Пропущены', buckets.skipped, '—'), section('Ошибки', buckets.error, '—'), section('Отменены / не дошли', buckets.cancelled, '—')), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    style: {
      width: '100%',
      marginTop: 12,
      padding: 12,
      borderRadius: 12,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u0417\u0430\u043A\u0440\u044B\u0442\u044C")));
}
function _scopePickerSummary(selectedCount, totalCount) {
  if (!totalCount || selectedCount >= totalCount) return 'все';
  if (selectedCount <= 0) return 'ничего';
  return `${selectedCount} из ${totalCount}`;
}
function AutoRefreshScopePickerModal({
  title,
  hint,
  accent,
  options,
  selectedIds,
  onClose,
  onApply
}) {
  const [draft, setDraft] = useStateMd(() => new Set(selectedIds));
  const toggle = id => {
    const key = String(id);
    setDraft(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);else next.add(key);
      return next;
    });
  };
  const selectAll = () => setDraft(new Set(options.map(o => String(o.id))));
  const clearAll = () => setDraft(new Set());
  const apply = () => {
    onApply(draft);
    onClose();
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 110,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.72)',
      padding: 16
    },
    onClick: e => {
      if (e.target === e.currentTarget) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": true,
    onClick: e => e.stopPropagation(),
    style: {
      width: '100%',
      maxWidth: 520,
      borderRadius: 16,
      border: '1px solid var(--line)',
      background: 'rgba(18,20,28,0.98)',
      padding: 20,
      boxShadow: '0 24px 56px rgba(0,0,0,0.65)'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: '0 0 8px',
      fontSize: 17,
      color: '#fff'
    }
  }, title), hint ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 14px',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, hint) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 14
    }
  }, options.map(o => /*#__PURE__*/React.createElement(Pill, {
    key: o.id,
    active: draft.has(String(o.id)),
    onClick: () => toggle(o.id),
    dot: o.color
  }, o.glyph ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      marginRight: 6
    }
  }, o.glyph) : null, o.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: selectAll,
    style: {
      padding: '8px 12px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 12
    }
  }, "\u0412\u0441\u0435"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: clearAll,
    style: {
      padding: '8px 12px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 12
    }
  }, "\u0421\u0431\u0440\u043E\u0441")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      justifyContent: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer',
      fontSize: 13
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: apply,
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: 'none',
      background: accent,
      color: '#000',
      cursor: 'pointer',
      fontSize: 13,
      fontWeight: 600
    }
  }, "\u0413\u043E\u0442\u043E\u0432\u043E"))));
}
function ScheduleModal({
  accent,
  onDataChanged,
  onClose
}) {
  const isMobile = useIsMobile(760);
  const SKIP_OPTIONS = [0, 1, 3, 6, 12, 24];
  const platformOptions = React.useMemo(() => {
    const known = [['tiktok', 'TikTok'], ['instagram', 'Instagram'], ['youtube', 'YouTube'], ['telegram', 'Telegram'], ['x', 'X (Twitter)'], ['threads', 'Threads'], ['facebook', 'Facebook'], ['rumble', 'Rumble'], ['reddit', 'Reddit']];
    const map = new Map(known.map(([id, label]) => [id, {
      id,
      label,
      color: PLATFORM_COLORS[id] || '#9ca3af'
    }]));
    for (const p of PLATFORMS) {
      if (!map.has(p.id)) map.set(p.id, {
        id: p.id,
        label: p.label,
        color: p.color || '#9ca3af'
      });
    }
    return Array.from(map.values());
  }, []);
  const profileOptions = React.useMemo(() => (PROFILES || []).map(p => ({
    id: String(p.id),
    label: p.label,
    color: p.color
  })), []);
  const [loading, setLoading] = useStateMd(true);
  const [saving, setSaving] = useStateMd(false);
  const [status, setStatus] = useStateMd(null);
  const [mode, setMode] = useStateMd('times');
  const [auto, setAuto] = useStateMd(false);
  const [intervalHours, setIntervalHours] = useStateMd(6);
  const [skipRecent, setSkipRecent] = useStateMd(0);
  const [selectedTimes, setSelectedTimes] = useStateMd([]);
  const [customScheduleSlots, setCustomScheduleSlots] = useStateMd([]);
  const [timesModalOpen, setTimesModalOpen] = useStateMd(false);
  const [platformsModalOpen, setPlatformsModalOpen] = useStateMd(false);
  const [profilesModalOpen, setProfilesModalOpen] = useStateMd(false);
  const [selectedPlatforms, setSelectedPlatforms] = useStateMd(() => new Set(platformOptions.map(p => p.id)));
  const [selectedProfiles, setSelectedProfiles] = useStateMd(() => new Set(profileOptions.map(p => p.id)));
  const [telegramEnabled, setTelegramEnabled] = useStateMd(false);
  const [telegramChatIds, setTelegramChatIds] = useStateMd([]);
  const [telegramNewChatId, setTelegramNewChatId] = useStateMd('');
  const [telegramTesting, setTelegramTesting] = useStateMd(false);
  const [warmEnabled, setWarmEnabled] = useStateMd(true);
  const [includeHiddenPlatform, setIncludeHiddenPlatform] = useStateMd(false);
  const [includeHiddenProfile, setIncludeHiddenProfile] = useStateMd(false);
  const [reportDownloading, setReportDownloading] = useStateMd(false);
  const [runBusy, setRunBusy] = useStateMd(false);
  const [runDetailOpen, setRunDetailOpen] = useStateMd(false);
  const prevRunningRef = React.useRef(false);
  const refreshAutoStatus = async () => {
    const st = await _fetchJson('/api/accounts/auto-refresh-status/').catch(() => null);
    setStatus(st);
    return st;
  };
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [sched, st] = await Promise.all([_fetchJson('/api/accounts/schedule/'), _fetchJson('/api/accounts/auto-refresh-status/').catch(() => null)]);
        if (!mounted || !sched) return;
        setMode(sched.mode || 'times');
        setAuto(!!sched.enabled);
        setIntervalHours(Number(sched.interval_hours || 6));
        setSkipRecent(Number(sched.skip_recent_hours ?? 0));
        const activeTimes = _scheduleTimesFromServer(sched);
        setSelectedTimes(activeTimes);
        setCustomScheduleSlots(activeTimes.filter(t => !DEFAULT_AUTO_REFRESH_TIMES.includes(t)));
        setTelegramEnabled(!!sched.auto_refresh_telegram_enabled);
        const tgIds = Array.isArray(sched.auto_refresh_telegram_chat_ids) && sched.auto_refresh_telegram_chat_ids.length ? sched.auto_refresh_telegram_chat_ids.map(x => String(x).trim()).filter(Boolean) : String(sched.auto_refresh_telegram_chat_id || '').trim() ? [String(sched.auto_refresh_telegram_chat_id).trim()] : [];
        setTelegramChatIds(tgIds);
        setTelegramNewChatId('');
        setWarmEnabled(sched.refresh_warm_enabled !== false);
        setIncludeHiddenPlatform(!!sched.include_hidden_platform_accounts);
        setIncludeHiddenProfile(!!sched.include_hidden_profile_accounts);
        const srvPlat = Array.isArray(sched.auto_refresh_platforms) ? sched.auto_refresh_platforms : [];
        const allPlat = platformOptions.map(p => p.id);
        setSelectedPlatforms(new Set(srvPlat.length ? srvPlat : allPlat));
        const srvProf = Array.isArray(sched.auto_refresh_profile_ids) ? sched.auto_refresh_profile_ids.map(x => String(x)) : [];
        const allProf = profileOptions.map(p => p.id);
        setSelectedProfiles(new Set(srvProf.length ? srvProf : allProf));
        setStatus(st);
      } catch (e) {
        await uiAlert(`Не удалось загрузить расписание: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    if (!status?.is_running && !runBusy) return undefined;
    const timer = setInterval(() => {
      void refreshAutoStatus();
    }, 7500);
    return () => clearInterval(timer);
  }, [status?.is_running, runBusy]);
  useEffect(() => {
    const wasRunning = !!prevRunningRef.current;
    const isRunning = !!status?.is_running;
    if (wasRunning && !isRunning) {
      void refreshAutoStatus();
      void onDataChanged?.();
    }
    prevRunningRef.current = isRunning;
  }, [status?.is_running, onDataChanged]);
  const buildSchedulePayload = (timesOverride = null) => {
    const times = mode === 'times' ? _sortScheduleTimes(timesOverride ?? selectedTimes) : [];
    const allPlat = platformOptions.map(p => p.id);
    const auto_refresh_platforms = selectedPlatforms.size >= allPlat.length ? [] : Array.from(selectedPlatforms);
    const allProf = profileOptions.map(p => p.id);
    const auto_refresh_profile_ids = selectedProfiles.size >= allProf.length ? [] : Array.from(selectedProfiles).map(id => id === 'none' ? 'none' : Number(id));
    return {
      enabled: auto,
      mode,
      interval_hours: Math.max(1, Number(intervalHours || 1)),
      skip_recent_hours: Math.max(0, Number(skipRecent ?? 0)),
      refresh_warm_enabled: !!warmEnabled,
      auto_refresh_telegram_enabled: !!telegramEnabled,
      auto_refresh_telegram_chat_ids: telegramChatIds.map(x => String(x).trim()).filter(Boolean),
      include_hidden_platform_accounts: includeHiddenPlatform,
      include_hidden_profile_accounts: includeHiddenProfile,
      auto_refresh_platforms,
      auto_refresh_profile_ids,
      times
    };
  };
  const platformSummary = _scopePickerSummary(selectedPlatforms.size, platformOptions.length);
  const profileSummary = _scopePickerSummary(selectedProfiles.size, profileOptions.length);
  const saveSchedule = async ({
    silent = false,
    timesOverride = null
  } = {}) => {
    if (!silent) setSaving(true);
    try {
      await _postJson('/api/accounts/schedule/', buildSchedulePayload(timesOverride));
      await onDataChanged?.();
      if (!silent) await uiAlert('Расписание сохранено.', 'Расписание');
    } catch (e) {
      if (!silent) await uiAlert(`Ошибка сохранения: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      throw e;
    } finally {
      if (!silent) setSaving(false);
    }
  };
  const persistTimeSlots = async nextTimes => {
    if (mode !== 'times') return;
    try {
      await saveSchedule({
        silent: true,
        timesOverride: nextTimes
      });
    } catch {
      await uiAlert('Не удалось сохранить время на сервер. Нажмите «Сохранить» внизу окна.', 'Расписание');
    }
  };
  const pillsRowTimes = _sortScheduleTimes([...DEFAULT_AUTO_REFRESH_TIMES, ...customScheduleSlots]);
  const toggleTime = timeValue => {
    const t = String(timeValue || '').trim();
    if (!/^\d{2}:\d{2}$/.test(t)) return;
    const cur = _sortScheduleTimes(selectedTimes);
    const next = cur.includes(t) ? cur.filter(x => x !== t) : _sortScheduleTimes([...cur, t]);
    setSelectedTimes(next);
    void persistTimeSlots(next);
  };
  const runNow = async () => {
    setRunBusy(true);
    try {
      // Ensure skip/include settings are persisted before manual start.
      await saveSchedule({
        silent: true
      });
      const candidates = _apiBaseCandidates();
      let started = false;
      let alreadyRunning = false;
      let lastErr = null;
      for (const base of candidates) {
        try {
          const res = await fetch(`${base}/api/accounts/auto-refresh-run-now/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: '{}'
          });
          let body = null;
          try {
            body = await res.json();
          } catch {}
          if (res.ok) {
            started = !!(body?.started ?? true);
            break;
          }
          if (res.status === 409) {
            alreadyRunning = true;
            break;
          }
          throw new Error(body?.detail || `HTTP ${res.status}`);
        } catch (e) {
          lastErr = e;
        }
      }
      await new Promise(r => setTimeout(r, 500));
      await refreshAutoStatus();
      if (alreadyRunning) {
        await uiAlert('Автообновление уже выполняется.', 'Автообновление');
      } else if (started) {
        await uiAlert('Автообновление запущено.', 'Автообновление');
      } else if (lastErr) {
        throw new Error(_apiTunnelDeadHint(lastErr instanceof Error ? lastErr : new Error(String(lastErr))));
      }
    } catch (e) {
      await uiAlert(`Не удалось запустить: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setRunBusy(false);
    }
  };
  const stopNow = async () => {
    try {
      if (status?.active_pipeline === 'refresh_all') {
        await _postJson('/api/accounts/refresh-all-stop/', {});
      } else {
        await _postJson('/api/accounts/auto-refresh-stop/', {});
      }
      const st = await _fetchJson('/api/accounts/auto-refresh-status/').catch(() => null);
      setStatus(st);
      await uiAlert('Остановка отправлена.', 'Автообновление');
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e || '');
      if (msg.includes('HTTP 409')) {
        const st = await _fetchJson('/api/accounts/auto-refresh-status/').catch(() => null);
        setStatus(st);
        await uiAlert('Автообновление сейчас не выполняется.', 'Автообновление');
        return;
      }
      await uiAlert(`Не удалось остановить: ${msg}`, 'Ошибка');
    }
  };
  const addTelegramChatId = () => {
    const cid = String(telegramNewChatId || '').trim();
    if (!cid) return;
    if (!/^-?\d{1,20}$/.test(cid)) {
      void uiAlert('Chat ID — только цифры (для групп может быть минус в начале).', 'Telegram');
      return;
    }
    if (telegramChatIds.includes(cid)) {
      setTelegramNewChatId('');
      return;
    }
    setTelegramChatIds(prev => [...prev, cid]);
    setTelegramNewChatId('');
  };
  const removeTelegramChatId = idx => {
    setTelegramChatIds(prev => prev.filter((_, i) => i !== idx));
  };
  const testTelegram = async () => {
    const ids = telegramChatIds.map(x => String(x).trim()).filter(Boolean);
    if (!ids.length) return;
    setTelegramTesting(true);
    try {
      const res = await _postJson('/api/accounts/schedule/telegram-test/', {
        chat_ids: ids
      });
      await uiAlert(res?.detail || 'Тестовое сообщение отправлено в Telegram.', 'Telegram');
    } catch (e) {
      await uiAlert(`Не удалось отправить: ${e instanceof Error ? e.message : String(e)}`, 'Telegram');
    } finally {
      setTelegramTesting(false);
    }
  };
  const downloadLastAutoRefreshReport = async () => {
    setReportDownloading(true);
    try {
      const candidates = _apiBaseCandidates();
      let blob = null;
      let lastStatus = 0;
      for (const base of candidates) {
        try {
          const res = await fetch(`${base}/api/accounts/auto-refresh-report/`);
          lastStatus = res.status;
          if (!res.ok) continue;
          blob = await res.blob();
          break;
        } catch (_) {}
      }
      if (!blob) {
        if (lastStatus === 404) {
          throw new Error('Отчёт не найден. Если запуск был прерван перезапуском бэка, новый CSV мог не успеть сохраниться.');
        }
        throw new Error(`HTTP ${lastStatus || 0}`);
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `auto-refresh-report-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      await uiAlert(`Не удалось скачать отчёт: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setReportDownloading(false);
    }
  };
  if (loading) {
    return /*#__PURE__*/React.createElement(ModalShell, {
      title: "\u0420\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u0435 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0439",
      kicker: "AUTOMATION",
      accent: accent,
      width: 620,
      onClose: onClose
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono",
      style: {
        color: 'var(--ink-mute)'
      }
    }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430\u2026"));
  }
  return /*#__PURE__*/React.createElement(ModalShell, {
    title: "\u0420\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u0435 \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0439",
    kicker: "AUTOMATION",
    accent: accent,
    width: 620,
    onClose: onClose
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '14px 16px',
      borderRadius: 12,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 500
    }
  }, "\u0410\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0435"), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      const next = !auto;
      setAuto(next);
      if (next && mode === 'times' && selectedTimes.length === 0) {
        setSelectedTimes([...DEFAULT_AUTO_REFRESH_TIMES]);
      }
    },
    style: {
      width: 50,
      height: 26,
      borderRadius: 999,
      background: auto ? '#4ade80' : 'rgba(255,255,255,0.1)',
      border: 'none',
      cursor: 'pointer',
      position: 'relative',
      transition: 'all .2s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 3,
      left: auto ? 27 : 3,
      width: 20,
      height: 20,
      borderRadius: 999,
      background: '#fff',
      transition: 'all .2s'
    }
  }))), !auto && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 14px',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, "\u0410\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0435 \u0432\u044B\u043A\u043B\u044E\u0447\u0435\u043D\u043E \u2014 \u043D\u0430 \u0431\u0440\u043E\u0434\u043A\u0430\u0441\u0442\u0435 \u0431\u0443\u0434\u0435\u0442 ", /*#__PURE__*/React.createElement("span", {
    className: "mono"
  }, "AUTO \xB7 OFF"), ", \u0441\u043B\u043E\u0442\u044B \u043F\u043E \u0432\u0440\u0435\u043C\u0435\u043D\u0438 \u043D\u0435 \u0437\u0430\u043F\u0443\u0441\u043A\u0430\u044E\u0442\u0441\u044F. \u0412\u043A\u043B\u044E\u0447\u0438\u0442\u0435 \u043F\u0435\u0440\u0435\u043A\u043B\u044E\u0447\u0430\u0442\u0435\u043B\u044C \u0432\u044B\u0448\u0435 \u0438 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \xAB\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C\xBB, \u0447\u0442\u043E\u0431\u044B \u0437\u0430\u0434\u0430\u0442\u044C \u0440\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u0435."), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid var(--line)',
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: 'var(--ink)',
      marginBottom: 6
    }
  }, "CSV-\u043E\u0442\u0447\u0451\u0442 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442\u0441\u044F \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u0435\u0441\u043A\u0438 \u043F\u043E\u0441\u043B\u0435 \u043A\u0430\u0436\u0434\u043E\u0433\u043E \u043F\u0440\u043E\u0433\u043E\u043D\u0430."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      marginBottom: 12,
      lineHeight: 1.5
    }
  }, "\u0424\u0430\u0439\u043B \u043C\u043E\u0436\u043D\u043E \u0441\u043A\u0430\u0447\u0430\u0442\u044C \u043D\u0438\u0436\u0435 \u043F\u043E\u0441\u043B\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043D\u0438\u044F \u0437\u0430\u043F\u0443\u0441\u043A\u0430."), status?.has_csv_report && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 10,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: downloadLastAutoRefreshReport,
    disabled: reportDownloading,
    style: {
      padding: '9px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13,
      opacity: reportDownloading ? 0.6 : 1
    }
  }, reportDownloading ? 'Скачиваю…' : 'Скачать отчёт последнего автообновления (CSV)'), status?.report_generated_at && /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)'
    }
  }, "\u0421\u0444\u043E\u0440\u043C\u0438\u0440\u043E\u0432\u0430\u043D: ", new Date(status.report_generated_at).toLocaleString('ru-RU')))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid var(--line)',
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'flex-start',
      cursor: 'pointer',
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    onClick: () => setTelegramEnabled(v => !v),
    style: {
      width: 18,
      height: 18,
      borderRadius: 5,
      background: telegramEnabled ? '#4ade80' : 'transparent',
      border: '1px solid #4ade80',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      marginTop: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#000',
      fontSize: 11,
      fontWeight: 800
    }
  }, telegramEnabled ? '✓' : '')), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: 'var(--ink)'
    }
  }, "\u041E\u0442\u043F\u0440\u0430\u0432\u043B\u044F\u0442\u044C \u043E\u0442\u0447\u0451\u0442 \u0432 Telegram"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.5
    }
  }, "Токен бота: TELEGRAM_BOT_TOKEN в backend/.env"))), telegramChatIds.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      marginBottom: 10
    }
  }, telegramChatIds.map((cid, idx) => /*#__PURE__*/React.createElement("div", {
    key: `${cid}-${idx}`,
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      flex: 1,
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(0,0,0,0.2)',
      color: 'var(--ink)',
      fontSize: 13
    }
  }, cid), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => removeTelegramChatId(idx),
    "aria-label": "Удалить chat ID",
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid rgba(239,68,68,0.45)',
      background: 'rgba(239,68,68,0.1)',
      color: '#fecaca',
      cursor: 'pointer',
      fontSize: 13
    }
  }, "Удалить")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap',
      alignItems: 'center',
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    value: telegramNewChatId,
    onChange: e => setTelegramNewChatId(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        addTelegramChatId();
      }
    },
    placeholder: "Chat ID",
    className: "mono",
    style: {
      flex: '1 1 160px',
      minWidth: 120,
      padding: '10px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(0,0,0,0.2)',
      color: 'var(--ink)',
      fontSize: 13
    }
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: addTelegramChatId,
    disabled: !telegramNewChatId.trim(),
    style: {
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13,
      opacity: !telegramNewChatId.trim() ? 0.5 : 1
    }
  }, "Добавить"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: testTelegram,
    disabled: telegramTesting || !telegramChatIds.length,
    style: {
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13,
      opacity: telegramTesting || !telegramChatIds.length ? 0.5 : 1
    }
  }, telegramTesting ? '…' : 'Проверить Telegram')), (status?.last_telegram_error || '') && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 12,
      color: '#f87171',
      lineHeight: 1.45
    }
  }, status.last_telegram_error)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid var(--line)',
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'flex-start',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("span", {
    onClick: () => setWarmEnabled(v => !v),
    style: {
      width: 18,
      height: 18,
      borderRadius: 5,
      background: warmEnabled ? '#4ade80' : 'transparent',
      border: '1px solid #4ade80',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      marginTop: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#000',
      fontSize: 11,
      fontWeight: 800
    }
  }, warmEnabled ? '✓' : '')), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: 'var(--ink)'
    }
  }, "\u041F\u0440\u043E\u0433\u0440\u0435\u0432 Facebook"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.5
    }
  }, "Reels \u0432\u043E 2-\u0439 \u0432\u043A\u043B\u0430\u0434\u043A\u0435 \u043F\u0430\u0440\u0430\u043B\u043B\u0435\u043B\u044C\u043D\u043E \u0441\u044A\u0451\u043C\u0443 FB (\u043F\u043E\u043A\u0430 \u0438\u0434\u0451\u0442 \u043F\u0440\u043E\u0433\u043E\u043D). TikTok \u2014 manage.py warm_tiktok_session.")))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid var(--line)',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 16,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center',
      cursor: 'pointer',
      color: 'var(--ink-dim)',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includeHiddenPlatform,
    onChange: e => setIncludeHiddenPlatform(e.target.checked)
  }), "\u0423\u0447\u0438\u0442\u044B\u0432\u0430\u0442\u044C \u0441\u043A\u0440\u044B\u0442\u044B\u0435 \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u044B"), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center',
      cursor: 'pointer',
      color: 'var(--ink-dim)',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includeHiddenProfile,
    onChange: e => setIncludeHiddenProfile(e.target.checked)
  }), "\u0423\u0447\u0438\u0442\u044B\u0432\u0430\u0442\u044C \u0441\u043A\u0440\u044B\u0442\u044B\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u0438"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      padding: 4,
      borderRadius: 12,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)',
      marginBottom: 16
    }
  }, [['interval', 'Каждые N часов'], ['times', 'В определённое время']].map(([id, l]) => /*#__PURE__*/React.createElement("button", {
    key: id,
    onClick: () => setMode(id),
    style: {
      flex: 1,
      padding: '10px 14px',
      borderRadius: 9,
      border: 'none',
      cursor: 'pointer',
      background: mode === id ? '#fff' : 'transparent',
      color: mode === id ? '#000' : 'var(--ink-dim)',
      fontSize: 13,
      fontWeight: 500
    }
  }, l))), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 10,
      opacity: auto ? 1 : 0.55
    }
  }, "\u0412\u0420\u0415\u041C\u042F \u041E\u0411\u041D\u041E\u0412\u041B\u0415\u041D\u0418\u042F \xB7 MSK"), mode === 'times' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      alignItems: 'center',
      marginBottom: 8,
      opacity: auto ? 1 : 0.55,
      pointerEvents: 'auto'
    }
  }, pillsRowTimes.map(t => /*#__PURE__*/React.createElement(Pill, {
    key: t,
    active: selectedTimes.includes(t),
    onClick: () => toggleTime(t),
    title: !auto ? `${t}: в черновике расписания (AUTO выкл — слот не запускается)` : selectedTimes.includes(t) ? `${t}: в расписании (нажмите, чтобы убрать)` : `${t}: не в расписании (нажмите, чтобы добавить)`
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono"
  }, t))), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setTimesModalOpen(true),
    disabled: false,
    title: 'Управление временем автообновления',
    "aria-label": "\u0423\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u0438\u0435 \u0432\u0440\u0435\u043C\u0435\u043D\u0435\u043C \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F",
    style: {
      width: 40,
      height: 40,
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink-dim)',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: auto ? 'pointer' : 'default',
      flexShrink: 0,
      opacity: auto ? 1 : 0.5
    }
  }, /*#__PURE__*/React.createElement(ClockIcon, {
    size: 18
  }))), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 18px',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, auto ? 'Нажмите на время — включить или выключить слот (серый = выключен); изменения сразу пишутся на сервер. Дополнительные слоты — по иконке часов.' : 'Белый слот = сохранённое время (сразу на сервер). Пока AUTO выкл, по расписанию ничего не запускается. Включите переключатель выше и нажмите «Сохранить».'), timesModalOpen && /*#__PURE__*/React.createElement(ScheduleTimesEditorModal, {
    accent: accent,
    customSlots: customScheduleSlots,
    onClose: () => setTimesModalOpen(false),
    onApply: nextCustom => {
      const prevCustom = customScheduleSlots;
      const removed = prevCustom.filter(c => !nextCustom.includes(c));
      const added = nextCustom.filter(c => !prevCustom.includes(c));
      setCustomScheduleSlots(_sortScheduleTimes(nextCustom));
      setSelectedTimes(prev => {
        let next = prev.filter(t => !removed.includes(t));
        for (const t of added) {
          if (!next.includes(t)) next = [...next, t];
        }
        return _sortScheduleTimes(next);
      });
    }
  })) : /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: 1,
    max: 48,
    value: intervalHours,
    onChange: e => setIntervalHours(Number(e.target.value || 1)),
    style: {
      width: '100%',
      marginBottom: 18,
      padding: '11px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink)',
      fontSize: 13,
      fontFamily: 'JetBrains Mono, monospace'
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 10
    }
  }, "\u041E\u0425\u0412\u0410\u0422 \u0410\u0412\u0422\u041E\u041E\u0411\u041D\u041E\u0412\u041B\u0415\u041D\u0418\u042F"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setPlatformsModalOpen(true),
    title: "\u041A\u0430\u043A\u0438\u0435 \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u044B \u0443\u0447\u0430\u0441\u0442\u0432\u0443\u044E\u0442 \u0432 \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438",
    style: {
      padding: '10px 14px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: accent,
      display: 'inline-block'
    }
  }), "\u041F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u044B \xB7 ", platformSummary), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setProfilesModalOpen(true),
    title: "\u041A\u0430\u043A\u0438\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u0438 \u0443\u0447\u0430\u0441\u0442\u0432\u0443\u044E\u0442 \u0432 \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438",
    style: {
      padding: '10px 14px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 13,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: '#4ade80',
      display: 'inline-block'
    }
  }), "\u041F\u0440\u043E\u0444\u0438\u043B\u0438 \xB7 ", profileSummary)), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 18px',
      fontSize: 12,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, "\u041F\u0443\u0441\u0442\u043E\u0439 \u0432\u044B\u0431\u043E\u0440 \u0432\u043D\u0443\u0442\u0440\u0438 \u043A\u043D\u043E\u043F\u043A\u0438 = \xAB\u0432\u0441\u0435\xBB. \u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u0435 \u0440\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u0435, \u0447\u0442\u043E\u0431\u044B \u0437\u0430\u043F\u0438\u0441\u0430\u0442\u044C \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440. \xAB\u0417\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u0441\u0435\u0439\u0447\u0430\u0441\xBB \u0442\u043E\u0436\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442 \u044D\u0442\u0438 \u043D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438."), platformsModalOpen && /*#__PURE__*/React.createElement(AutoRefreshScopePickerModal, {
    title: "\u041F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u044B \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F",
    hint: "\u0412\u043A\u043B\u044E\u0447\u0451\u043D\u043D\u044B\u0435 \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C\u044B \u043F\u043E\u043F\u0430\u0434\u0443\u0442 \u0432 \u043F\u0440\u043E\u0433\u043E\u043D \u043F\u043E \u0440\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u044E \u0438 \xAB\u0417\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u0441\u0435\u0439\u0447\u0430\u0441\xBB. \u0415\u0441\u043B\u0438 \u0432\u044B\u0431\u0440\u0430\u043D\u044B \u0432\u0441\u0435 \u2014 \u043E\u0433\u0440\u0430\u043D\u0438\u0447\u0435\u043D\u0438\u044F \u043D\u0435\u0442.",
    accent: accent,
    options: platformOptions.map(p => ({
      id: p.id,
      label: p.label,
      color: p.color,
      glyph: /*#__PURE__*/React.createElement(PlatformGlyph, {
        id: p.id,
        size: 14
      })
    })),
    selectedIds: selectedPlatforms,
    onClose: () => setPlatformsModalOpen(false),
    onApply: next => setSelectedPlatforms(next)
  }), profilesModalOpen && /*#__PURE__*/React.createElement(AutoRefreshScopePickerModal, {
    title: "\u041F\u0440\u043E\u0444\u0438\u043B\u0438 \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F",
    hint: "\u0412\u043A\u043B\u044E\u0447\u0451\u043D\u043D\u044B\u0435 \u043F\u0440\u043E\u0444\u0438\u043B\u0438 (\u0438 \xAB\u0411\u0435\u0437 \u043F\u0440\u043E\u0444\u0438\u043B\u044F\xBB) \u043E\u043F\u0440\u0435\u0434\u0435\u043B\u044F\u044E\u0442, \u043A\u0430\u043A\u0438\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B \u043E\u0431\u043D\u043E\u0432\u043B\u044F\u044E\u0442\u0441\u044F \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u0435\u0441\u043A\u0438.",
    accent: accent,
    options: profileOptions,
    selectedIds: selectedProfiles,
    onClose: () => setProfilesModalOpen(false),
    onApply: next => setSelectedProfiles(next)
  }), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 10
    }
  }, "\u041F\u0420\u041E\u041F\u0423\u0421\u041A\u0410\u0422\u042C \u041D\u0415\u0414\u0410\u0412\u041D\u041E \u041E\u0411\u041D\u041E\u0412\u041B\u0401\u041D\u041D\u042B\u0415"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 18
    }
  }, SKIP_OPTIONS.map(h => /*#__PURE__*/React.createElement(Pill, {
    key: h,
    active: skipRecent === h,
    onClick: () => setSkipRecent(h)
  }, h === 0 ? 'Не пропускать' : `< ${h}ч`))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      flexDirection: isMobile ? 'column' : 'row'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: saveSchedule,
    disabled: saving,
    style: {
      flex: 1,
      padding: 14,
      borderRadius: 12,
      background: accent,
      color: '#000',
      border: 'none',
      fontSize: 14,
      fontWeight: 600,
      cursor: 'pointer',
      opacity: saving ? 0.6 : 1
    }
  }, saving ? 'Сохранение…' : 'Сохранить'), /*#__PURE__*/React.createElement("button", {
    onClick: runNow,
    disabled: runBusy || !!status?.is_running,
    style: {
      flex: 1,
      padding: 14,
      borderRadius: 12,
      background: '#4ade80',
      color: '#000',
      border: 'none',
      fontSize: 14,
      fontWeight: 600,
      cursor: runBusy || status?.is_running ? 'default' : 'pointer',
      opacity: runBusy || status?.is_running ? 0.7 : 1
    }
  }, runBusy ? 'Запуск…' : status?.is_running ? status.active_pipeline === 'refresh_all' ? 'Сбор всех уже идёт' : 'Уже запущено' : 'Запустить сейчас'), /*#__PURE__*/React.createElement("button", {
    onClick: stopNow,
    disabled: !status?.is_running,
    style: {
      flex: 1,
      padding: 14,
      borderRadius: 12,
      background: '#ef4444',
      color: '#fff',
      border: 'none',
      fontSize: 14,
      fontWeight: 600,
      cursor: status?.is_running ? 'pointer' : 'default',
      opacity: status?.is_running ? 1 : 0.45
    }
  }, "\u041E\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u044C")), status && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u0421\u0442\u0430\u0442\u0443\u0441:", ' ', !status.is_running ? 'не идет' : status.active_pipeline === 'refresh_all' ? 'идёт сбор всех' : status.active_pipeline === 'bulk_refresh' ? 'идёт обновление выбранных' : 'идёт автообновление', ' ', "\xB7 ", status.processed_accounts || 0, "/", status.total_accounts || 0), /*#__PURE__*/React.createElement("span", null, Math.max(0, Math.min(100, Number(status.progress_percent || 0))), "%")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6,
      height: 8,
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${Math.max(0, Math.min(100, Number(status.progress_percent || 0)))}%`,
      height: '100%',
      borderRadius: 999,
      background: status.is_running ? 'linear-gradient(90deg, #22c55e, #4ade80)' : 'rgba(148,163,184,0.45)',
      transition: 'width 260ms ease'
    }
  })), Number(status.skip_recent_hours_config || 0) > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 11,
      color: '#fde68a',
      lineHeight: 1.45
    }
  }, "\u041D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0432\u043A\u043B\u044E\u0447\u0451\u043D \u043F\u0440\u043E\u043F\u0443\u0441\u043A \u043D\u0435\u0434\u0430\u0432\u043D\u0438\u0445: < ", status.skip_recent_hours_config, " \u0447 \u2014 \u0442\u0430\u043A\u0438\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B \u043D\u0435 \u0434\u0435\u0440\u0433\u0430\u044E\u0442 \u0431\u0440\u0430\u0443\u0437\u0435\u0440. \u0412\u044B\u0431\u0435\u0440\u0438\u0442\u0435 \xAB\u041D\u0435 \u043F\u0440\u043E\u043F\u0443\u0441\u043A\u0430\u0442\u044C\xBB \u0438 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \xAB\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C\xBB (\u043A\u043D\u043E\u043F\u043A\u0430 \xAB\u0417\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u0441\u0435\u0439\u0447\u0430\u0441\xBB \u043F\u0435\u0440\u0435\u0434 \u0437\u0430\u043F\u0443\u0441\u043A\u043E\u043C \u0442\u043E\u0436\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442 \u0444\u043E\u0440\u043C\u0443).")), (status?.last_telegram_error || '') && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 11,
      color: '#f87171',
      lineHeight: 1.45
    }
  }, status.last_telegram_error), (status?.is_running || Array.isArray(status?.run_detail?.items) && status.run_detail.items.length > 0 || status?.run_detail?.warm && typeof status.run_detail.warm === 'object' && Object.keys(status.run_detail.warm).length > 0) && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setRunDetailOpen(true),
    style: {
      width: '100%',
      marginTop: 12,
      padding: '11px 14px',
      borderRadius: 12,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 14,
      fontWeight: 500
    }
  }, "\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435: \u043F\u0440\u043E\u0433\u0440\u0435\u0432, \u043E\u0447\u0435\u0440\u0435\u0434\u044C \u0438 \u0441\u043B\u043E\u0442\u044B"), runDetailOpen && /*#__PURE__*/React.createElement(AutoRefreshRunDetailOverlay, {
    status: status,
    accent: accent,
    onClose: () => setRunDetailOpen(false),
    refreshAutoStatus: refreshAutoStatus
  }));
}
function ProfilePicker({
  accent,
  value = 'none',
  onChange
}) {
  const isMobile = useIsMobile(760);
  const [open, setOpen] = useStateMd(false);
  const profileOptions = (PROFILES || []).filter(p => String(p?.id) !== 'none');
  const opts = [{
    id: 'none',
    label: 'Без профиля',
    color: '#525a70'
  }, ...profileOptions];
  const sel = opts.find(o => o.id === value) || opts[0];
  if (isMobile) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        padding: '8px 10px',
        borderRadius: 999,
        border: '1px solid var(--line-2)',
        background: 'rgba(255,255,255,0.04)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 999,
        background: sel.color,
        boxShadow: `0 0 8px ${sel.color}`,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("select", {
      value: value,
      onChange: e => onChange?.(e.target.value),
      style: {
        width: '100%',
        minWidth: 0,
        border: 'none',
        outline: 'none',
        background: 'transparent',
        color: 'var(--ink)',
        fontSize: 13,
        fontFamily: 'inherit',
        appearance: 'none',
        WebkitAppearance: 'none',
        MozAppearance: 'none'
      }
    }, opts.map(o => /*#__PURE__*/React.createElement("option", {
      key: o.id,
      value: o.id,
      style: {
        color: '#ffffff',
        background: '#1f2937'
      }
    }, o.label)))));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(!open),
    style: {
      width: '100%',
      padding: '8px 14px',
      borderRadius: 999,
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      border: '1px solid var(--line-2)',
      fontSize: 13,
      fontWeight: 500,
      cursor: 'pointer',
      fontFamily: 'inherit',
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: sel.color,
      boxShadow: `0 0 8px ${sel.color}`
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      minWidth: 0,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, sel.label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 9,
      color: 'var(--ink-mute)',
      marginLeft: 'auto'
    }
  }, "\u25BC")), open && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 'calc(100% + 6px)',
      left: isMobile ? 'auto' : 0,
      right: isMobile ? 0 : 'auto',
      zIndex: 20,
      minWidth: isMobile ? 160 : 180,
      width: isMobile ? 'min(86vw, 320px)' : 'auto',
      padding: 6,
      borderRadius: 12,
      background: 'rgba(20,22,28,0.96)',
      backdropFilter: 'blur(12px)',
      border: '1px solid var(--line-2)',
      boxShadow: '0 12px 32px rgba(0,0,0,0.4)'
    }
  }, opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.id,
    onClick: () => {
      onChange?.(o.id);
      setOpen(false);
    },
    style: {
      width: '100%',
      padding: '8px 12px',
      borderRadius: 8,
      background: value === o.id ? 'rgba(255,255,255,0.06)' : 'transparent',
      border: 'none',
      cursor: 'pointer',
      fontSize: 13,
      fontFamily: 'inherit',
      color: value === o.id ? '#fff' : 'var(--ink-dim)',
      textAlign: 'left',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: o.color,
      boxShadow: `0 0 8px ${o.color}`
    }
  }), o.label))));
}
function AddOneInline({
  accent,
  onDataChanged,
  onClose
}) {
  const isCompact = useIsMobile(1160);
  const isMobile = useIsMobile(760);
  const [platform, setPlatform] = useStateMd(PLATFORMS[0]?.id || 'tiktok');
  const [username, setUsername] = useStateMd('');
  const [profileId, setProfileId] = useStateMd('none');
  const [busy, setBusy] = useStateMd(false);
  const [profileBusy, setProfileBusy] = useStateMd(false);
  const [profileEditorOpen, setProfileEditorOpen] = useStateMd(false);
  const createProfileInline = async ({
    name,
    color
  }) => {
    const profileName = String(name || '').trim();
    if (!profileName) return;
    setProfileBusy(true);
    try {
      const created = await _postJson('/api/accounts/profiles/', {
        name: profileName,
        color: color || '#6366f1'
      });
      const createdId = created?.id != null ? String(created.id) : null;
      await onDataChanged?.();
      if (createdId) setProfileId(createdId);
      await uiAlert(`Профиль "${profileName}" добавлен.`, 'Профили');
      setProfileEditorOpen(false);
    } catch (e) {
      await uiAlert(`Не удалось добавить профиль: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setProfileBusy(false);
    }
  };
  const addOne = async () => {
    if (!username.trim()) return;
    setBusy(true);
    try {
      await _postJson('/api/accounts/', {
        platform,
        username: username.trim().replace(/^@/, ''),
        profile_id: profileId === 'none' ? null : Number(profileId)
      });
      await onDataChanged?.();
      setUsername('');
      await uiAlert('Аккаунт добавлен.', 'Добавление аккаунта');
    } catch (e) {
      await uiAlert(`Ошибка добавления: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      setBusy(false);
    }
  };
  return /*#__PURE__*/React.createElement(ModalShell, {
    title: "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442",
    kicker: "QUICK ADD",
    accent: accent,
    width: 900,
    offsetY: "-20%",
    onClose: onClose
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isCompact ? '1fr' : '160px minmax(240px,1fr) minmax(240px,280px)',
      gap: 14,
      alignItems: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "\u041F\u041B\u0410\u0422\u0424\u041E\u0420\u041C\u0410"), /*#__PURE__*/React.createElement("select", {
    value: platform,
    onChange: e => setPlatform(e.target.value),
    style: {
      width: '100%',
      padding: '11px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink)',
      fontSize: 13,
      fontFamily: 'inherit'
    }
  }, PLATFORMS.map(p => /*#__PURE__*/React.createElement("option", {
    key: p.id,
    value: p.id,
    style: {
      color: '#ffffff',
      background: '#374151'
    }
  }, p.label)))), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "USERNAME"), /*#__PURE__*/React.createElement("input", {
    value: username,
    onChange: e => setUsername(e.target.value),
    placeholder: "@username",
    style: {
      width: '100%',
      padding: '11px 14px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line-2)',
      color: 'var(--ink)',
      fontSize: 14,
      fontFamily: 'JetBrains Mono, monospace'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "\u041F\u0420\u041E\u0424\u0418\u041B\u042C"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: isCompact ? '1fr auto' : 'minmax(0,1fr) auto',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(ProfilePicker, {
    accent: accent,
    value: profileId,
    onChange: setProfileId
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => setProfileEditorOpen(true),
    disabled: profileBusy,
    style: {
      padding: '11px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: profileBusy ? 'default' : 'pointer',
      fontSize: 13,
      opacity: profileBusy ? 0.7 : 1
    }
  }, profileBusy ? '...' : '+ Добавить')))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginTop: 22,
      justifyContent: 'flex-end',
      flexDirection: isMobile ? 'column' : 'row'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      padding: '10px 20px',
      borderRadius: 10,
      background: 'transparent',
      border: '1px solid var(--line)',
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: addOne,
    disabled: busy,
    style: {
      padding: '10px 24px',
      borderRadius: 10,
      background: accent,
      color: '#000',
      border: 'none',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      opacity: busy ? 0.6 : 1
    }
  }, busy ? 'Добавление...' : 'Добавить')), profileEditorOpen && /*#__PURE__*/React.createElement(ProfileEditorModal, {
    accent: accent,
    mode: "create",
    busy: profileBusy,
    onSubmit: createProfileInline,
    onClose: () => {
      if (!profileBusy) setProfileEditorOpen(false);
    }
  }));
}
function RefreshAllModal({
  accent,
  onDataChanged,
  onClose
}) {
  const platformOptions = React.useMemo(() => {
    const known = [['tiktok', 'TikTok'], ['instagram', 'Instagram'], ['youtube', 'YouTube'], ['telegram', 'Telegram'], ['x', 'X (Twitter)'], ['threads', 'Threads'], ['facebook', 'Facebook'], ['rumble', 'Rumble'], ['reddit', 'Reddit']];
    const map = new Map(known.map(([id, label]) => [id, {
      id,
      label,
      color: PLATFORM_COLORS[id] || '#9ca3af'
    }]));
    for (const p of PLATFORMS) {
      if (!map.has(p.id)) map.set(p.id, {
        id: p.id,
        label: p.label,
        color: p.color || '#9ca3af'
      });
    }
    return Array.from(map.values());
  }, []);
  const [selectedPlatforms, setSelectedPlatforms] = useStateMd(() => new Set(platformOptions.map(p => p.id)));
  const [selectedProfiles, setSelectedProfiles] = useStateMd(() => new Set(PROFILES.map(p => p.id)));
  const [availability, setAvailability] = useStateMd('all'); // all | avail | unavail
  const [search, setSearch] = useStateMd('');
  const [includeHiddenPlatform, setIncludeHiddenPlatform] = useStateMd(false);
  const [includeHiddenProfile, setIncludeHiddenProfile] = useStateMd(false);
  const [includeUnavailable, setIncludeUnavailable] = useStateMd(false);
  const [selectedIds, setSelectedIds] = useStateMd(() => new Set(ACCOUNTS.map(a => a.id)));
  const [busy, setBusy] = useStateMd(false);
  const [runStatus, setRunStatus] = useStateMd(null);
  const [downloadCsvAfter, setDownloadCsvAfter] = useStateMd(false);
  const [updatedSortOrder, setUpdatedSortOrder] = useStateMd('desc'); // desc=newest first, asc=oldest first
  const SKIP_OPTIONS = [0, 1, 3, 6, 12, 24];
  const [skipRecent, setSkipRecent] = useStateMd(0);
  const [warmEnabled, setWarmEnabled] = useStateMd(true);
  const [runDetailOpen, setRunDetailOpen] = useStateMd(false);
  const [csvImport, setCsvImport] = useStateMd(null);
  const refreshModeRef = React.useRef(null);
  const pendingRunRef = React.useRef(null);
  const prevRunningRef = React.useRef(false);
  /** true только после is_running для текущего pendingRunRef (не ловим хвост прошлого прогона). */
  const runSeenActiveRef = React.useRef(false);
  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const sched = await _fetchJson('/api/accounts/schedule/');
        if (!mounted || !sched) return;
        setSkipRecent(Number(sched.skip_recent_hours ?? 0));
        setWarmEnabled(sched.refresh_warm_enabled !== false);
      } catch (_) {/* ignore */}
    })();
    return () => {
      mounted = false;
    };
  }, []);
  const persistRefreshSettings = async () => {
    await _postJson('/api/accounts/schedule/', {
      skip_recent_hours: skipRecent,
      refresh_warm_enabled: !!warmEnabled
    });
  };
  const refreshRunStatus = async () => {
    const st = await _fetchJson('/api/accounts/auto-refresh-status/').catch(() => null);
    setRunStatus(st);
    return st;
  };
  const pipelineLabel = st => {
    if (!st?.is_running) return 'не идёт';
    if (st.active_pipeline === 'refresh_all') return 'идёт сбор всех';
    if (st.active_pipeline === 'bulk_refresh') return 'идёт обновление выбранных';
    return 'идёт автообновление по расписанию';
  };
  React.useEffect(() => {
    let mounted = true;
    (async () => {
      const st = await refreshRunStatus();
      if (!mounted || !st?.is_running) return;
      if (st.active_pipeline === 'refresh_all') {
        refreshModeRef.current = 'refresh_all';
      } else if (st.active_pipeline === 'bulk_refresh') {
        refreshModeRef.current = 'bulk';
        setBusy(true);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);
  const REFRESH_RESTART_ERR = 'Автообновление было прервано перезапуском процесса.';
  const runDetailCounts = st => {
    const items = st?.run_detail?.items || [];
    let done = 0;
    let failed = 0;
    let active = 0;
    for (const it of items) {
      const s = String(it?.status || '');
      if (s === 'done' || s === 'skipped') done += 1;else if (s === 'error') {
        failed += 1;
        done += 1;
      } else if (s === 'cancelled') done += 1;else if (s === 'running' || s === 'queued') active += 1;
    }
    return {
      done,
      failed,
      active,
      total: items.length
    };
  };
  const bulkRunStillGoing = st => {
    if (!st || st.finished_at) return false;
    const c = runDetailCounts(st);
    const totalN = Number(st.total_accounts || c.total || 0);
    if (c.active > 0) return true;
    if (totalN > 0 && Number(st.processed_accounts || 0) < totalN) return true;
    return false;
  };
  React.useEffect(() => {
    const pending = pendingRunRef.current;
    const shouldPoll = !!runStatus?.is_running || pending?.mode === 'bulk' && bulkRunStillGoing(runStatus);
    if (!shouldPoll) return undefined;
    const timer = setInterval(() => {
      void refreshRunStatus();
    }, 2000);
    return () => clearInterval(timer);
  }, [runStatus?.is_running, runStatus?.processed_accounts, runStatus?.finished_at, runStatus?.run_detail]);
  const finishBulkRefreshRun = async pending => {
    const lastSt = await refreshRunStatus().catch(() => null);
    const counts = runDetailCounts(lastSt);
    const failedN = Math.max(Number(lastSt?.failed_accounts || 0), counts.failed);
    const successN = Math.max(Number(lastSt?.success_accounts || 0), counts.done - counts.failed);
    let warn = lastSt && lastSt.last_error ? String(lastSt.last_error) : '';
    if (warn === REFRESH_RESTART_ERR && bulkRunStillGoing(lastSt)) warn = '';
    const totalN = Number(lastSt?.total_accounts || pending?.idsCount || counts.total || 0);
    if (totalN > 0) {
      if (warn || failedN > 0) {
        await uiAlert(`Обновление завершено. Успешно: ${successN} из ${totalN}.${failedN > 0 ? ` Ошибок: ${failedN}.` : ''}${warn ? `\n\n${warn}` : ''}`, 'Обновить аккаунты');
      } else {
        await uiAlert(`Успешно обновлено: ${successN} из ${totalN}`, 'Обновить аккаунты');
      }
    }
    await onDataChanged?.();
    onClose?.();
  };
  const finishRefreshAllRun = async pending => {
    const lastSt = await refreshRunStatus().catch(() => null);
    if (pending?.downloadCsv && lastSt?.has_csv_report) {
      try {
        const blob = await _fetchBlobWithApiBases('/api/accounts/refresh-all-report/');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `refresh-report-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
        a.click();
        URL.revokeObjectURL(url);
      } catch (_) {/* отчёт на сервере всё равно есть */}
    }
    const failedN = Number(lastSt?.failed_accounts || 0);
    const warn = lastSt && lastSt.last_error ? String(lastSt.last_error) : '';
    const n = Number(pending?.idsCount || 0);
    if (warn || failedN > 0) {
      await uiAlert(`Сбор завершён.${failedN > 0 ? ` Ошибок по аккаунтам: ${failedN}.` : ''}${warn ? `\n\n${warn}` : ''}\n\nРасширенный CSV-отчёт сохранён на сервере.`, 'Обновить аккаунты');
    } else if (n > 0) {
      await uiAlert(`Обновлено: ${n}. Расширенный CSV с приростами и временем по аккаунтам сохранён на сервере.`, 'Обновить аккаунты');
    }
    await onDataChanged?.();
    onClose?.();
  };
  React.useEffect(() => {
    const wasRunning = !!prevRunningRef.current;
    const isRunning = !!runStatus?.is_running;
    const pending = pendingRunRef.current;
    if (pending && isRunning) {
      runSeenActiveRef.current = true;
    }
    if (runSeenActiveRef.current && wasRunning && !isRunning && pending) {
      if (pending.mode === 'bulk' && bulkRunStillGoing(runStatus)) {
        prevRunningRef.current = false;
        return;
      }
      pendingRunRef.current = null;
      refreshModeRef.current = null;
      runSeenActiveRef.current = false;
      setBusy(false);
      if (pending.mode === 'refresh_all') {
        void finishRefreshAllRun(pending);
      } else if (pending.mode === 'bulk') {
        void finishBulkRefreshRun(pending);
      }
    } else if (wasRunning && !isRunning && !pending && refreshModeRef.current) {
      refreshModeRef.current = null;
      void onDataChanged?.();
    }
    prevRunningRef.current = isRunning;
  }, [runStatus?.is_running, runStatus?.processed_accounts, runStatus?.finished_at, runStatus?.run_detail, onDataChanged, onClose]);
  const opInProgress = !!runStatus?.is_running;
  const togglePlatform = id => {
    setSelectedPlatforms(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);else next.add(id);
      return next;
    });
  };
  const toggleProfile = id => {
    setSelectedProfiles(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);else next.add(id);
      return next;
    });
  };
  const filtered = ACCOUNTS.filter(a => {
    if (!includeHiddenPlatform && a.isPlatformHidden) return false;
    if (!includeHiddenProfile && a.isProfileHidden) return false;
    if (availability === 'all' && !includeUnavailable && a.unavailable) return false;
    if (selectedPlatforms.size === 0) return false;
    if (!selectedPlatforms.has(a.platform)) return false;
    if (selectedProfiles.size > 0 && !selectedProfiles.has(a.profile)) return false;
    if (availability === 'avail' && a.unavailable) return false;
    if (availability === 'unavail' && !a.unavailable) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      if (!a.name.toLowerCase().includes(q) && !a.handle.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  const filteredSorted = [...filtered].sort((a, b) => {
    const at = Number(a.updatedTs || 0);
    const bt = Number(b.updatedTs || 0);
    return updatedSortOrder === 'asc' ? at - bt : bt - at;
  });
  const filteredIds = filteredSorted.map(a => a.id);
  const selectedVisibleCount = filteredIds.reduce((acc, id) => acc + (selectedIds.has(id) ? 1 : 0), 0);
  const allVisibleSelected = filteredIds.length > 0 && selectedVisibleCount === filteredIds.length;
  const setAllVisible = checked => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      for (const id of filteredIds) {
        if (checked) next.add(id);else next.delete(id);
      }
      return next;
    });
  };
  const syncSelectionToFilter = () => setAllVisible(true);
  const clearSelection = () => setAllVisible(false);
  const toggleOne = id => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);else next.add(id);
      return next;
    });
  };
  const selectedCount = Array.from(selectedIds).filter(id => filtered.some(a => a.id === id)).length;
  const runRefreshClicks = async () => {
    const ids = Array.from(selectedIds).filter(id => filtered.some(a => a.id === id));
    if (ids.length === 0) {
      await uiAlert('Ничего не выбрано.', 'Переходы');
      return;
    }
    if (opInProgress) {
      await uiAlert('Сейчас идёт сбор/обновление аккаунтов. Дождитесь завершения или остановите его.', 'Переходы');
      return;
    }
    setBusy(true);
    try {
      const res = await _postJson('/api/accounts/refresh-link-clicks/', {
        ids
      });
      const updated = Number(res?.updated || 0);
      const changed = Number(res?.changed ?? updated);
      const skipped = Number(res?.skipped || 0);
      const total = Number(res?.total || ids.length);
      const errs = Array.isArray(res?.errors) ? res.errors : [];
      let msg = `Обработано: ${updated} из ${total}. Изменилось значений: ${changed}.`;
      if (skipped > 0) {
        msg += `\nПропущено (нет URL профиля или данных Links): ${skipped}.`;
      }
      if (updated > 0 && changed === 0) {
        msg += '\n\nЧисла в БД совпали с ответом Links — прирост на экране мог не измениться.';
      }
      if (errs.length) {
        const last = errs[errs.length - 1];
        msg += `\n\nОшибок: ${errs.length}.`;
        if (last?.detail) msg += `\nПоследняя: ${last.detail}`;
      }
      await onDataChanged?.();
      await uiAlert(msg, errs.length ? 'Переходы — с ошибками' : 'Переходы');
    } catch (e) {
      await uiAlert(`Ошибка: ${e instanceof Error ? e.message : String(e)}`, 'Переходы');
    } finally {
      setBusy(false);
    }
  };
  const runRefresh = async () => {
    const ids = Array.from(selectedIds).filter(id => filtered.some(a => a.id === id));
    if (ids.length === 0) {
      await uiAlert('Ничего не выбрано.', 'Обновить аккаунты');
      return;
    }
    if (opInProgress) {
      await uiAlert('Уже выполняется обновление. Дождитесь завершения или нажмите «Остановить».', 'Обновить аккаунты');
      return;
    }
    setBusy(true);
    prevRunningRef.current = false;
    runSeenActiveRef.current = false;
    try {
      await persistRefreshSettings();
      const selectedAll = ids.length === ACCOUNTS.length;
      const mode = selectedAll ? 'refresh_all' : 'bulk';
      refreshModeRef.current = mode;
      pendingRunRef.current = {
        mode,
        downloadCsv: downloadCsvAfter,
        idsCount: ids.length
      };
      if (selectedAll) {
        const params = new URLSearchParams();
        if (includeUnavailable) params.set('include_unavailable_accounts', '1');
        if (downloadCsvAfter) params.set('download_csv', '1');
        const qs = params.toString();
        await _postJson(`/api/accounts/refresh_all/${qs ? `?${qs}` : ''}`, {});
        await refreshRunStatus();
        return;
      } else {
        await _postJson('/api/accounts/bulk-refresh/', {
          ids
        });
        runSeenActiveRef.current = true;
        prevRunningRef.current = true;
        await refreshRunStatus();
        return;
      }
    } catch (e) {
      pendingRunRef.current = null;
      runSeenActiveRef.current = false;
      await uiAlert(`Ошибка обновления: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    } finally {
      const pendingMode = pendingRunRef.current?.mode;
      if (pendingMode !== 'refresh_all' && pendingMode !== 'bulk') {
        refreshModeRef.current = null;
        setBusy(false);
      }
    }
  };
  const downloadSavedRefreshReport = async () => {
    try {
      const blob = await _fetchBlobWithApiBases('/api/accounts/refresh-all-report/');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `refresh-all-saved-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      await uiAlert(`Нет сохранённого отчёта или ошибка сети: ${e instanceof Error ? e.message : String(e)}`, 'CSV отчёт');
    }
  };
  const refreshLastAutoRefreshErrors = async () => {
    let j;
    try {
      j = await _fetchJson('/api/accounts/auto-refresh-last-error-ids/');
    } catch (e) {
      await uiAlert(`Не удалось получить список: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      return;
    }
    const serverIds = Array.isArray(j?.ids) ? j.ids.map(x => Number(x)).filter(n => Number.isFinite(n)) : [];
    const known = new Set(ACCOUNTS.map(a => a.id));
    const ids = serverIds.filter(id => known.has(id));
    if (serverIds.length === 0) {
      await uiAlert('В последнем завершённом автообновлении по расписанию не было аккаунтов со статусом «ошибка», либо прогон ещё ни разу не завершился.', 'Повторить ошибки');
      return;
    }
    if (ids.length === 0) {
      await uiAlert('Аккаунты с ошибками из последнего автообновления отсутствуют в текущем списке (удалены или не попали в выгрузку API).', 'Повторить ошибки');
      return;
    }
    setBusy(true);
    prevRunningRef.current = false;
    runSeenActiveRef.current = false;
    refreshModeRef.current = 'bulk';
    pendingRunRef.current = {
      mode: 'bulk',
      idsCount: ids.length
    };
    try {
      await _postJson('/api/accounts/bulk-refresh/', {
        ids
      });
      runSeenActiveRef.current = true;
      prevRunningRef.current = true;
      await refreshRunStatus();
    } catch (e) {
      pendingRunRef.current = null;
      runSeenActiveRef.current = false;
      refreshModeRef.current = null;
      await uiAlert(`Ошибка обновления: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
      setBusy(false);
    }
  };
  const stopRefresh = async () => {
    try {
      const pipeline = runStatus?.active_pipeline || (refreshModeRef.current === 'refresh_all' ? 'refresh_all' : 'bulk_refresh');
      if (pipeline === 'refresh_all') {
        await _postJson('/api/accounts/refresh-all-stop/', {});
        await uiAlert('Остановка сбора всех запрошена. Текущие аккаунты в воркерах завершатся, затем процесс остановится.', 'Остановка обновления');
      } else {
        await _postJson('/api/accounts/auto-refresh-stop/', {});
        await uiAlert('Остановка запрошена. Текущий аккаунт завершится и процесс остановится.', 'Остановка обновления');
      }
      await refreshRunStatus();
    } catch (e) {
      await uiAlert(`Не удалось остановить: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    }
  };
  const exportCsv = async () => {
    try {
      const blob = await _fetchBlobWithApiBases('/api/accounts/export-snapshot/');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `dashboard-snapshot-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      await uiAlert(`Не удалось экспортировать CSV: ${e instanceof Error ? e.message : String(e)}`, 'Ошибка');
    }
  };
  const importCsv = async () => {
    if (csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing')) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv,text/csv';
    input.onchange = async () => {
      const f = input.files?.[0];
      if (!f) return;
      const fileLabel = `${f.name} (${(f.size / (1024 * 1024)).toFixed(1)} МБ)`;
      setCsvImport({
        phase: 'upload',
        percent: 0,
        fileName: f.name,
        fileLabel,
        statusText: 'Подготовка…'
      });
      try {
        const summary = await _postFormDataJsonWithUploadProgress('/api/accounts/import-snapshot/', f, 'file', {
          onUploadPercent: (pct, loaded, total) => {
            const mbLoaded = (loaded / (1024 * 1024)).toFixed(1);
            const mbTotal = total ? (total / (1024 * 1024)).toFixed(1) : '?';
            setCsvImport({
              phase: 'upload',
              percent: pct,
              fileName: f.name,
              fileLabel,
              statusText: `Загрузка на сервер… ${pct}% (${mbLoaded} / ${mbTotal} МБ)`
            });
          },
          onPhase: phase => {
            if (phase === 'processing') {
              setCsvImport({
                phase: 'processing',
                percent: 92,
                fileName: f.name,
                fileLabel,
                statusText: 'Обработка CSV на сервере (большие файлы — несколько минут)…'
              });
            }
          }
        });
        await onDataChanged?.();
        const {
          msg,
          errs
        } = _formatImportSummaryMessage(summary);
        const donePhase = errs.length ? 'done-warn' : 'done-ok';
        setCsvImport({
          phase: donePhase,
          percent: 100,
          fileName: f.name,
          fileLabel,
          statusText: errs.length ? 'Импорт завершён с ошибками' : 'Импорт успешно завершён',
          summary: msg,
          errorCount: errs.length
        });
        await uiAlert(errs.length ? `${msg}\n\nПроверьте список ошибок в модалке.` : `${msg}\n\nДанные на сервере обновлены.`, errs.length ? 'CSV — с ошибками' : 'Импорт завершён');
      } catch (e) {
        const errMsg = e instanceof Error ? e.message : String(e);
        setCsvImport({
          phase: 'error',
          percent: 0,
          fileName: f.name,
          fileLabel,
          statusText: 'Импорт не выполнен',
          summary: errMsg
        });
        await uiAlert(`Не удалось импортировать CSV: ${errMsg}`, 'Ошибка');
      }
    };
    input.click();
  };
  return /*#__PURE__*/React.createElement(ModalShell, {
    title: "\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C \u0432\u044B\u0431\u0440\u0430\u043D\u043D\u044B\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B",
    kicker: "REFRESH",
    accent: accent,
    width: 860,
    onClose: onClose
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 8,
      marginBottom: 10,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: exportCsv,
    disabled: csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing'),
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      opacity: csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing') ? 0.5 : 1
    }
  }, "\u042D\u043A\u0441\u043F\u043E\u0440\u0442 CSV"), /*#__PURE__*/React.createElement("button", {
    onClick: importCsv,
    disabled: csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing'),
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing') ? 'default' : 'pointer',
      opacity: csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing') ? 0.5 : 1
    }
  }, csvImport && (csvImport.phase === 'upload' || csvImport.phase === 'processing') ? 'Импорт…' : 'Импорт CSV')), csvImport && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14,
      padding: '12px 14px',
      borderRadius: 12,
      border: `1px solid ${csvImport.phase === 'error' ? '#ef444455' : csvImport.phase === 'done-warn' ? '#f59e0b55' : csvImport.phase === 'done-ok' ? '#4ade8055' : 'var(--line)'}`,
      background: csvImport.phase === 'error' ? 'rgba(239,68,68,0.08)' : csvImport.phase === 'done-ok' ? 'rgba(74,222,128,0.08)' : csvImport.phase === 'done-warn' ? 'rgba(245,158,11,0.08)' : 'rgba(255,255,255,0.02)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 10,
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: 'var(--ink)'
    }
  }, csvImport.statusText), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginTop: 4
    }
  }, csvImport.fileLabel || csvImport.fileName)), (csvImport.phase === 'done-ok' || csvImport.phase === 'done-warn' || csvImport.phase === 'error') && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setCsvImport(null),
    "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C",
    style: {
      width: 28,
      height: 28,
      borderRadius: 8,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-mute)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, "\u2715")), (csvImport.phase === 'upload' || csvImport.phase === 'processing') && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${Math.max(4, Math.min(100, Number(csvImport.percent || 0)))}%`,
      height: '100%',
      borderRadius: 999,
      background: csvImport.phase === 'processing' ? 'linear-gradient(90deg, #38bdf8, #4ade80, #38bdf8)' : 'linear-gradient(90deg, #22c55e, #4ade80)',
      backgroundSize: csvImport.phase === 'processing' ? '200% 100%' : '100% 100%',
      animation: csvImport.phase === 'processing' ? 'csvImportPulse 1.2s ease infinite' : 'none',
      transition: 'width 200ms ease'
    }
  })), /*#__PURE__*/React.createElement("style", null, `@keyframes csvImportPulse { 0% { background-position: 0% 50%; } 100% { background-position: 200% 50%; } }`)), (csvImport.phase === 'done-ok' || csvImport.phase === 'done-warn' || csvImport.phase === 'error') && csvImport.summary && /*#__PURE__*/React.createElement("pre", {
    style: {
      margin: '10px 0 0',
      padding: '10px 12px',
      borderRadius: 8,
      background: 'rgba(0,0,0,0.2)',
      border: '1px solid var(--line)',
      fontSize: 11,
      lineHeight: 1.45,
      color: 'var(--ink-dim)',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      maxHeight: 220,
      overflow: 'auto',
      fontFamily: 'JetBrains Mono, monospace'
    }
  }, csvImport.summary)), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 8
    }
  }, "\u041F\u041B\u0410\u0422\u0424\u041E\u0420\u041C\u042B"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 12
    }
  }, platformOptions.map(p => /*#__PURE__*/React.createElement(Pill, {
    key: p.id,
    active: selectedPlatforms.has(p.id),
    onClick: () => togglePlatform(p.id),
    dot: p.color
  }, p.label)), /*#__PURE__*/React.createElement("button", {
    onClick: () => setSelectedPlatforms(new Set(platformOptions.map(p => p.id))),
    style: {
      padding: '8px 12px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 12
    }
  }, "\u0412\u0441\u0435"), /*#__PURE__*/React.createElement("button", {
    onClick: () => setSelectedPlatforms(new Set()),
    style: {
      padding: '8px 12px',
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 12
    }
  }, "\u0421\u0431\u0440\u043E\u0441")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 12,
      display: 'grid',
      gridTemplateColumns: '1fr auto',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      padding: 10,
      border: '1px solid var(--line)',
      borderRadius: 10
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      color: 'var(--ink-dim)',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u0412\u043A\u043B\u044E\u0447\u0430\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B \u0441\u043A\u0440\u044B\u0442\u044B\u0445 \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C"), /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includeHiddenPlatform,
    onChange: e => setIncludeHiddenPlatform(e.target.checked)
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      color: 'var(--ink-dim)',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u0412\u043A\u043B\u044E\u0447\u0430\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B \u0441\u043A\u0440\u044B\u0442\u044B\u0445 \u043F\u0440\u043E\u0444\u0438\u043B\u0435\u0439"), /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includeHiddenProfile,
    onChange: e => setIncludeHiddenProfile(e.target.checked)
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      color: 'var(--ink-dim)',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u0423\u0447\u0438\u0442\u044B\u0432\u0430\u0442\u044C \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u043D\u044B\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B"), /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includeUnavailable,
    onChange: e => setIncludeUnavailable(e.target.checked)
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: syncSelectionToFilter,
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer'
    }
  }, "\u0412\u044B\u0431\u0440\u0430\u0442\u044C \u0432\u0441\u0435"), /*#__PURE__*/React.createElement("button", {
    onClick: clearSelection,
    style: {
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.03)',
      color: 'var(--ink)',
      cursor: 'pointer'
    }
  }, "\u0421\u043D\u044F\u0442\u044C \u0432\u0441\u0435"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 12
    }
  }, PROFILES.map(p => /*#__PURE__*/React.createElement(Pill, {
    key: p.id,
    active: selectedProfiles.has(p.id),
    onClick: () => toggleProfile(p.id),
    dot: p.color
  }, p.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: availability === 'all',
    onClick: () => setAvailability('all')
  }, "\u0412\u0441\u0435"), /*#__PURE__*/React.createElement(Pill, {
    active: availability === 'avail',
    onClick: () => setAvailability('avail')
  }, "\u0422\u043E\u043B\u044C\u043A\u043E \u0434\u043E\u0441\u0442\u0443\u043F\u043D\u044B\u0435"), /*#__PURE__*/React.createElement(Pill, {
    active: availability === 'unavail',
    onClick: () => setAvailability('unavail')
  }, "\u0422\u043E\u043B\u044C\u043A\u043E \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u043D\u044B\u0435")), /*#__PURE__*/React.createElement("input", {
    value: search,
    onChange: e => setSearch(e.target.value),
    placeholder: "\u041F\u043E\u0438\u0441\u043A: username, \u0438\u043C\u044F",
    style: {
      width: '100%',
      marginBottom: 10,
      padding: '10px 12px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid var(--line)',
      color: 'var(--ink)',
      fontSize: 13,
      fontFamily: 'inherit'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement(Pill, {
    active: updatedSortOrder === 'desc',
    onClick: () => setUpdatedSortOrder('desc')
  }, "\u0421\u043D\u0430\u0447\u0430\u043B\u0430 \u043D\u043E\u0432\u044B\u0435"), /*#__PURE__*/React.createElement(Pill, {
    active: updatedSortOrder === 'asc',
    onClick: () => setUpdatedSortOrder('asc')
  }, "\u0421\u043D\u0430\u0447\u0430\u043B\u0430 \u0441\u0442\u0430\u0440\u044B\u0435")), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 10,
      color: 'var(--ink-dim)',
      fontSize: 13,
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: allVisibleSelected,
    onChange: e => setAllVisible(e.target.checked)
  }), "\u0412\u044B\u0431\u0440\u0430\u0442\u044C \u0432\u0441\u0435 \u0432 \u0441\u043F\u0438\u0441\u043A\u0435 (", selectedVisibleCount, "/", filtered.length, ")"), /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 300,
      overflowY: 'auto',
      border: '1px solid var(--line)',
      borderRadius: 10,
      marginBottom: 12
    }
  }, filteredSorted.map(a => /*#__PURE__*/React.createElement("label", {
    key: a.id,
    style: {
      display: 'grid',
      gridTemplateColumns: '24px 1fr auto',
      gap: 10,
      padding: '10px 12px',
      borderBottom: '1px solid var(--line)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: selectedIds.has(a.id),
    onChange: () => toggleOne(a.id)
  }), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-dim)'
    }
  }, PLATFORM_META[a.platform]?.label || a.platform), " \xA0 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: '#fff'
    }
  }, a.name), " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-mute)'
    }
  }, a.handle)), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      color: 'var(--ink-mute)',
      fontSize: 12
    }
  }, a.updated)))), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      color: 'var(--ink-dim)',
      fontSize: 13,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: downloadCsvAfter,
    onChange: e => setDownloadCsvAfter(e.target.checked)
  }), "\u0421\u0440\u0430\u0437\u0443 \u0441\u043A\u0430\u0447\u0430\u0442\u044C CSV \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435 \u043F\u043E\u0441\u043B\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043D\u0438\u044F"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--ink-mute)',
      marginBottom: 10,
      lineHeight: 1.45
    }
  }, "\u041E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0435 (\u0438 \u0447\u0430\u0441\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432, \u0438 \u0432\u0441\u0435) \u0438\u0434\u0451\u0442 \u0432 \u0444\u043E\u043D\u0435: \u043F\u0440\u043E\u0433\u0440\u0435\u0441\u0441, \u043F\u0440\u043E\u0433\u0440\u0435\u0432 Facebook \u0438 \xAB\u041E\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u044C\xBB \u2014 \u0432 \u044D\u0442\u043E\u0439 \u043C\u043E\u0434\u0430\u043B\u043A\u0435. \u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043D\u043D\u044B\u0439 CSV-\u043E\u0442\u0447\u0451\u0442 \u0441 \u043F\u0440\u0438\u0440\u043E\u0441\u0442\u0430\u043C\u0438 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442\u0441\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0442\u043E\u043B\u044C\u043A\u043E \u043F\u0440\u0438 \u0441\u0431\u043E\u0440\u0435 \u0432\u0441\u0435\u0445 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432."), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      void downloadSavedRefreshReport();
    },
    style: {
      padding: '8px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      fontSize: 13,
      cursor: 'pointer',
      marginBottom: 8
    }
  }, "\u0421\u043A\u0430\u0447\u0430\u0442\u044C \u0441\u043E\u0445\u0440\u0430\u043D\u0451\u043D\u043D\u044B\u0439 \u043E\u0442\u0447\u0451\u0442 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0435\u0433\u043E \u0441\u0431\u043E\u0440\u0430 (CSV)"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: busy || opInProgress,
    onClick: () => {
      void refreshLastAutoRefreshErrors();
    },
    style: {
      padding: '8px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      fontSize: 13,
      cursor: busy || opInProgress ? 'default' : 'pointer',
      marginBottom: 12,
      display: 'block',
      opacity: busy || opInProgress ? 0.6 : 1
    }
  }, "\u041F\u043E\u0432\u0442\u043E\u0440\u0438\u0442\u044C \u043E\u0448\u0438\u0431\u043A\u0438 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0435\u0433\u043E \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginTop: -6,
      marginBottom: 12,
      lineHeight: 1.45
    }
  }, "\u0422\u0435 \u0436\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B, \u0447\u0442\u043E \u0441\u043E \u0441\u0442\u0430\u0442\u0443\u0441\u043E\u043C \xAB\u043E\u0448\u0438\u0431\u043A\u0430\xBB \u0432 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0435\u043C \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043D\u043D\u043E\u043C \u0430\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0438 \u043F\u043E \u0440\u0430\u0441\u043F\u0438\u0441\u0430\u043D\u0438\u044E (\u0438\u043B\u0438 \xAB\u0437\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u0441\u0435\u0439\u0447\u0430\u0441\xBB). \u0412 CSV-\u043E\u0442\u0447\u0451\u0442\u0435 \u044D\u0442\u043E\u0433\u043E \u043F\u0440\u043E\u0433\u043E\u043D\u0430 \u043E\u043D\u0438 \u0432 \u043A\u043E\u043B\u043E\u043D\u043A\u0435 \xABID \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430\xBB; \u0441\u043F\u0438\u0441\u043E\u043A ID \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442\u0441\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0434\u0430\u0436\u0435 \u0435\u0441\u043B\u0438 \u0432\u044B\u0433\u0440\u0443\u0437\u043A\u0430 CSV \u0432 \u0444\u0430\u0439\u043B \u043E\u0442\u043A\u043B\u044E\u0447\u0435\u043D\u0430 \u0432 \u043D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0430\u0445."), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.02)',
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'flex-start',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("span", {
    onClick: () => setWarmEnabled(v => !v),
    style: {
      width: 18,
      height: 18,
      borderRadius: 5,
      background: warmEnabled ? '#4ade80' : 'transparent',
      border: '1px solid #4ade80',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      marginTop: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#000',
      fontSize: 11,
      fontWeight: 800
    }
  }, warmEnabled ? '✓' : '')), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: 'var(--ink)'
    }
  }, "\u041F\u0440\u043E\u0433\u0440\u0435\u0432 Facebook"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginTop: 4,
      lineHeight: 1.45
    }
  }, "Reels \u0432\u043E 2-\u0439 \u0432\u043A\u043B\u0430\u0434\u043A\u0435 \u043F\u0430\u0440\u0430\u043B\u043B\u0435\u043B\u044C\u043D\u043E \u0441\u044A\u0451\u043C\u043E\u043C FB. TikTok \u2014 manage.py warm_tiktok_session. \u041F\u0435\u0440\u0435\u0434 \xAB\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C\xBB \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442\u0441\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440.")))), /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      letterSpacing: '0.2em',
      marginBottom: 10
    }
  }, "\u041F\u0420\u041E\u041F\u0423\u0421\u041A\u0410\u0422\u042C \u041D\u0415\u0414\u0410\u0412\u041D\u041E \u041E\u0411\u041D\u041E\u0412\u041B\u0401\u041D\u041D\u042B\u0415"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 10
    }
  }, SKIP_OPTIONS.map(h => /*#__PURE__*/React.createElement(Pill, {
    key: h,
    active: skipRecent === h,
    onClick: () => setSkipRecent(h)
  }, h === 0 ? 'Не пропускать' : `< ${h}ч`))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      marginBottom: 14,
      lineHeight: 1.45
    }
  }, "\u041E\u0431\u0449\u0430\u044F \u043D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0430 \u0441 \xAB\u0410\u0432\u0442\u043E\u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u0435\u043C\xBB. \u041F\u0435\u0440\u0435\u0434 \xAB\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C\xBB \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0435\u0442\u0441\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440. \u041D\u0435\u0434\u0430\u0432\u043D\u043E \u043E\u0431\u043D\u043E\u0432\u043B\u0451\u043D\u043D\u044B\u0435 \u043D\u0435 \u043E\u0442\u043A\u0440\u044B\u0432\u0430\u044E\u0442 \u0431\u0440\u0430\u0443\u0437\u0435\u0440."), (opInProgress || runStatus) && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14,
      padding: '12px 14px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.02)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-mute)',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", null, pipelineLabel(runStatus), opInProgress ? ` · ${runStatus?.processed_accounts || 0}/${runStatus?.total_accounts || 0}` : ''), opInProgress && /*#__PURE__*/React.createElement("span", null, Math.max(0, Math.min(100, Number(runStatus?.progress_percent || 0))), "%")), opInProgress && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      height: 8,
      borderRadius: 999,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${Math.max(0, Math.min(100, Number(runStatus?.progress_percent || 0)))}%`,
      height: '100%',
      borderRadius: 999,
      background: 'linear-gradient(90deg, #22c55e, #4ade80)',
      transition: 'width 260ms ease'
    }
  })), runStatus?.current_account && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 12,
      color: 'var(--ink-dim)',
      lineHeight: 1.4
    }
  }, "\u0421\u0435\u0439\u0447\u0430\u0441: ", /*#__PURE__*/React.createElement("span", {
    className: "mono"
  }, runStatus.current_account), runStatus.cancel_requested ? /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#fecaca'
    }
  }, " \xB7 \u043E\u0441\u0442\u0430\u043D\u043E\u0432\u043A\u0430\u2026") : null), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6,
      fontSize: 11,
      color: 'var(--ink-mute)',
      lineHeight: 1.45
    }
  }, "\u041F\u0440\u043E\u0433\u0440\u0435\u0441\u0441 \u0445\u0440\u0430\u043D\u0438\u0442\u0441\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u2014 \u043C\u043E\u0436\u043D\u043E \u0437\u0430\u043A\u0440\u044B\u0442\u044C \u0432\u043A\u043B\u0430\u0434\u043A\u0443 \u0438 \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u043C\u043E\u0434\u0430\u043B\u043A\u0443 \u0441\u043D\u043E\u0432\u0430."), Number(runStatus?.skip_recent_hours_config || 0) > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 11,
      color: '#fde68a',
      lineHeight: 1.45
    }
  }, "\u041D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0432\u043A\u043B\u044E\u0447\u0451\u043D \u043F\u0440\u043E\u043F\u0443\u0441\u043A \u043D\u0435\u0434\u0430\u0432\u043D\u0438\u0445: < ", runStatus.skip_recent_hours_config, " \u0447 \u2014 \u0442\u0430\u043A\u0438\u0435 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u044B \u043D\u0435 \u0434\u0435\u0440\u0433\u0430\u044E\u0442 \u0431\u0440\u0430\u0443\u0437\u0435\u0440. \u0412\u044B\u0431\u0435\u0440\u0438\u0442\u0435 \xAB\u041D\u0435 \u043F\u0440\u043E\u043F\u0443\u0441\u043A\u0430\u0442\u044C\xBB \u0438 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \xAB\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C\xBB."))), (runStatus?.is_running || Array.isArray(runStatus?.run_detail?.items) && runStatus.run_detail.items.length > 0 || runStatus?.run_detail?.warm && typeof runStatus.run_detail.warm === 'object' && Object.keys(runStatus.run_detail.warm).length > 0) && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setRunDetailOpen(true),
    style: {
      width: '100%',
      marginBottom: 14,
      padding: '11px 14px',
      borderRadius: 12,
      border: '1px solid var(--line)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--ink)',
      cursor: 'pointer',
      fontSize: 14,
      fontWeight: 500
    }
  }, "\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435: \u043F\u0440\u043E\u0433\u0440\u0435\u0432, \u043E\u0447\u0435\u0440\u0435\u0434\u044C \u0438 \u0441\u043B\u043E\u0442\u044B"), runDetailOpen && /*#__PURE__*/React.createElement(AutoRefreshRunDetailOverlay, {
    status: runStatus,
    accent: accent,
    onClose: () => setRunDetailOpen(false),
    refreshAutoStatus: refreshRunStatus
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, "\u0417\u0430\u043A\u0440\u044B\u0442\u044C"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8
    }
  }, opInProgress && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      void stopRefresh();
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid rgba(239,68,68,0.45)',
      background: 'rgba(239,68,68,0.12)',
      color: '#fecaca',
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, "\u041E\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u044C"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      void runRefreshClicks();
    },
    disabled: busy || opInProgress,
    title: "\u0417\u0430\u043F\u0440\u043E\u0441\u0438\u0442\u044C total_clicks \u0438\u0437 Links \u0434\u043B\u044F \u0432\u044B\u0431\u0440\u0430\u043D\u043D\u044B\u0445 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432 (\u0431\u0435\u0437 scrape \u043F\u043B\u0430\u0442\u0444\u043E\u0440\u043C)",
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid #a78bfa88',
      background: 'rgba(167,139,250,0.14)',
      color: '#e9d5ff',
      fontWeight: 600,
      cursor: busy || opInProgress ? 'default' : 'pointer',
      opacity: busy || opInProgress ? 0.6 : 1
    }
  }, busy && !opInProgress ? 'Переходы…' : `↻ Переходы (${selectedCount})`), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      void runRefresh();
    },
    disabled: busy || opInProgress,
    style: {
      padding: '10px 18px',
      borderRadius: 10,
      border: 'none',
      background: '#fff',
      color: '#000',
      fontWeight: 600,
      cursor: busy || opInProgress ? 'default' : 'pointer',
      opacity: busy || opInProgress ? 0.6 : 1
    }
  }, busy || opInProgress ? 'Обновление...' : `Обновить (${selectedCount})`))));
}
Object.assign(window, {
  ModalsScreen
});

// ===== app.jsx =====
// Root app — routes between TV broadcast and main interface screens, hosts Tweaks panel.

const {
  useState: useStateApp,
  useEffect: useEffectApp
} = React;
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "tv_mood": "mission",
  "accent": "#6aa9ff",
  "accounts_view": "table",
  "start_screen": "accounts"
} /*EDITMODE-END*/;
function NFUiHost() {
  const [alertState, setAlertState] = useStateApp(null); // {title,message,resolve}
  const [confirmState, setConfirmState] = useStateApp(null); // {title,message,resolve}
  const [promptState, setPromptState] = useStateApp(null); // {title,label,value,resolve}
  const [promptValue, setPromptValue] = useStateApp('');
  useEffectApp(() => {
    window.__nf_ui = {
      alert: (message, title = 'Уведомление') => new Promise(resolve => {
        setAlertState({
          message,
          title,
          resolve
        });
      }),
      confirm: (message, title = 'Подтверждение') => new Promise(resolve => {
        setConfirmState({
          message,
          title,
          resolve
        });
      }),
      prompt: (label, value = '', title = 'Ввод') => new Promise(resolve => {
        setPromptValue(value);
        setPromptState({
          label,
          title,
          resolve
        });
      })
    };
    return () => {
      delete window.__nf_ui;
    };
  }, []);
  return /*#__PURE__*/React.createElement(React.Fragment, null, alertState && /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: () => {
      alertState.resolve();
      setAlertState(null);
    }
  }, /*#__PURE__*/React.createElement(ModalShell, {
    title: alertState.title,
    kicker: "INFO",
    accent: "#6aa9ff",
    width: 460,
    onClose: () => {
      alertState.resolve();
      setAlertState(null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 14,
      marginBottom: 16,
      lineHeight: 1.5
    }
  }, alertState.message), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      alertState.resolve();
      setAlertState(null);
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: 'none',
      background: '#fff',
      color: '#000',
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, "\u041E\u041A")))), confirmState && /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: () => {
      confirmState.resolve(false);
      setConfirmState(null);
    }
  }, /*#__PURE__*/React.createElement(ModalShell, {
    title: confirmState.title,
    kicker: "CONFIRM",
    accent: "#6aa9ff",
    width: 500,
    onClose: () => {
      confirmState.resolve(false);
      setConfirmState(null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 14,
      marginBottom: 16,
      lineHeight: 1.5
    }
  }, confirmState.message), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      confirmState.resolve(false);
      setConfirmState(null);
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      confirmState.resolve(true);
      setConfirmState(null);
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: 'none',
      background: '#fff',
      color: '#000',
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, "\u041F\u043E\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044C")))), promptState && /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: () => {
      promptState.resolve(null);
      setPromptState(null);
    }
  }, /*#__PURE__*/React.createElement(ModalShell, {
    title: promptState.title,
    kicker: "INPUT",
    accent: "#6aa9ff",
    width: 520,
    onClose: () => {
      promptState.resolve(null);
      setPromptState(null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      color: 'var(--ink-dim)',
      fontSize: 13,
      marginBottom: 8
    }
  }, promptState.label), /*#__PURE__*/React.createElement("input", {
    value: promptValue,
    onChange: e => setPromptValue(e.target.value),
    autoFocus: true,
    style: {
      width: '100%',
      marginBottom: 16,
      padding: '11px 12px',
      borderRadius: 10,
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid var(--line)',
      color: 'var(--ink)',
      fontSize: 14,
      fontFamily: 'inherit'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      promptState.resolve(null);
      setPromptState(null);
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid var(--line)',
      background: 'transparent',
      color: 'var(--ink-dim)',
      cursor: 'pointer'
    }
  }, "\u041E\u0442\u043C\u0435\u043D\u0430"), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      promptState.resolve(promptValue);
      setPromptState(null);
    },
    style: {
      padding: '10px 16px',
      borderRadius: 10,
      border: 'none',
      background: '#fff',
      color: '#000',
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, "\u041E\u041A")))));
}
function _initialRouteFromUrl() {
  try {
    const q = new URLSearchParams(window.location.search);
    const r = (q.get('route') || q.get('screen') || '').trim().toLowerCase();
    if (['tv', 'accounts', 'analytics', 'settings', 'modals'].includes(r)) return r;
    const path = (window.location.pathname || '').replace(/\/+$/, '');
    if (path.endsWith('/analytics') || path === '/analytics') return 'analytics';
    if (path.endsWith('/accounts') || path === '/accounts') return 'accounts';
    if (path.endsWith('/settings') || path === '/settings') return 'settings';
    if (path.endsWith('/tv') || path === '/tv') return 'tv';
  } catch (_) {}
  return null;
}
function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = useStateApp(_initialRouteFromUrl() || tweaks.start_screen || 'tv');
  const [dataReady, setDataReady] = useStateApp(false);
  const [dataKey, setDataKey] = useStateApp(0);
  const [reloading, setReloading] = useStateApp(false);
  const [selectedAccountId, setSelectedAccountId] = useStateApp(null);
  const [globalModal, setGlobalModal] = useStateApp(null); // refresh_all | schedule | add_list | add_one
  const autoRefreshInFlightRef = React.useRef(false);

  // Auto-apply accent to CSS variables
  useEffectApp(() => {
    document.documentElement.style.setProperty('--accent', tweaks.accent);
  }, [tweaks.accent]);
  useEffectApp(() => {
    if (!_isEmbedMode()) return;
    const root = document.getElementById('root');
    const prevPb = document.body.style.paddingBottom;
    const prevHtmlH = document.documentElement.style.height;
    const prevHtmlMinH = document.documentElement.style.minHeight;
    const prevHtmlW = document.documentElement.style.width;
    const prevBodyH = document.body.style.height;
    const prevBodyMinH = document.body.style.minHeight;
    const prevBodyW = document.body.style.width;
    const prevBodyM = document.body.style.margin;
    const prevOx = document.body.style.overflowX;
    const prevRootH = root ? root.style.height : '';
    const prevRootMinH = root ? root.style.minHeight : '';
    document.documentElement.classList.add('nf-embed');
    document.documentElement.style.width = '100%';
    document.documentElement.style.height = '100%';
    document.documentElement.style.minHeight = '0';
    document.body.style.width = '100%';
    document.body.style.height = '100%';
    document.body.style.minHeight = '0';
    document.body.style.margin = '0';
    document.body.style.overflowX = 'hidden';
    document.body.style.paddingBottom = '0';
    if (root) {
      root.style.height = '100%';
      root.style.minHeight = '0';
      root.style.display = 'flex';
      root.style.flexDirection = 'column';
    }
    return () => {
      document.documentElement.classList.remove('nf-embed');
      document.body.style.paddingBottom = prevPb;
      document.documentElement.style.height = prevHtmlH;
      document.documentElement.style.minHeight = prevHtmlMinH;
      document.documentElement.style.width = prevHtmlW;
      document.body.style.height = prevBodyH;
      document.body.style.minHeight = prevBodyMinH;
      document.body.style.width = prevBodyW;
      document.body.style.margin = prevBodyM;
      document.body.style.overflowX = prevOx;
      if (root) {
        root.style.height = prevRootH;
        root.style.minHeight = prevRootMinH;
        root.style.display = '';
        root.style.flexDirection = '';
      }
    };
  }, []);
  useEffectApp(() => {
    let cancelled = false;
    loadDashboardData().catch(e => console.error('[new_frontend] failed to load API data', e)).finally(() => {
      if (!cancelled) {
        setDataReady(true);
        setDataKey(v => v + 1);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const reloadData = async () => {
    setReloading(true);
    try {
      await loadDashboardData();
      setDataKey(v => v + 1);
    } finally {
      setReloading(false);
    }
  };
  useEffectApp(() => {
    const intervalMs = route === 'tv' ? 15 * 1000 : 10 * 60 * 1000; // TV updates much faster
    const id = setInterval(async () => {
      if (autoRefreshInFlightRef.current) return;
      autoRefreshInFlightRef.current = true;
      try {
        await loadDashboardData();
        setDataKey(v => v + 1);
      } catch (e) {
        // Silent background refresh: keep UI running with last known data.
        console.warn('[new_frontend] background refresh failed', e);
      } finally {
        autoRefreshInFlightRef.current = false;
      }
    }, intervalMs);
    return () => clearInterval(id);
  }, [route]);

  // После полуночи по Москве summary должен отдать новые yesterday_* — подтягиваем даже на вкладках с редким автообновлением.
  useEffectApp(() => {
    let lastMsk = _mskCalendarDateKey();
    const id = setInterval(() => {
      const cur = _mskCalendarDateKey();
      if (cur === lastMsk) return;
      lastMsk = cur;
      if (autoRefreshInFlightRef.current) return;
      autoRefreshInFlightRef.current = true;
      (async () => {
        try {
          await loadDashboardData();
          setDataKey(v => v + 1);
        } catch (e) {
          console.warn('[new_frontend] calendar day change refresh failed', e);
        } finally {
          autoRefreshInFlightRef.current = false;
        }
      })();
    }, 30000);
    return () => clearInterval(id);
  }, []);
  useEffectApp(() => {
    if (route !== 'tv') return;
    if (autoRefreshInFlightRef.current) return;
    autoRefreshInFlightRef.current = true;
    (async () => {
      try {
        await loadDashboardData();
        setDataKey(v => v + 1);
      } catch (e) {
        console.warn('[new_frontend] tv immediate refresh failed', e);
      } finally {
        autoRefreshInFlightRef.current = false;
      }
    })();
  }, [route]);
  const ROUTES = [{
    id: 'tv',
    label: 'TV Broadcast'
  }, {
    id: 'accounts',
    label: 'Аккаунты'
  }, {
    id: 'account_detail',
    label: 'Аккаунт'
  }, {
    id: 'analytics',
    label: 'Аналитика'
  }, {
    id: 'settings',
    label: 'Настройки'
  }];
  if (!dataReady) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        color: 'var(--ink-dim)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "mono"
    }, "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430 \u0434\u0430\u043D\u043D\u044B\u0445..."));
  }
  return /*#__PURE__*/React.createElement(React.Fragment, null, route === 'tv' && /*#__PURE__*/React.createElement(TVScreen, {
    tweaks: tweaks,
    onExit: () => setRoute('accounts')
  }), route === 'accounts' && /*#__PURE__*/React.createElement(AccountsScreen, {
    key: `acc-${dataKey}`,
    tweaks: tweaks,
    onNavigate: setRoute,
    onDataChanged: reloadData,
    onOpenGlobalModal: setGlobalModal,
    onOpenAccount: id => {
      setSelectedAccountId(id);
      setRoute('account_detail');
    }
  }), route === 'account_detail' && selectedAccountId != null && /*#__PURE__*/React.createElement(AccountDetailScreen, {
    key: `detail-${selectedAccountId}-${dataKey}`,
    accountId: selectedAccountId,
    onBack: () => setRoute('accounts'),
    onDataChanged: reloadData
  }), route === 'analytics' && /*#__PURE__*/React.createElement(AnalyticsScreen, {
    key: `an-${dataKey}`,
    tweaks: tweaks,
    onOpenGlobalModal: setGlobalModal,
    onOpenAccount: id => {
      setSelectedAccountId(id);
      setRoute('account_detail');
    }
  }), route === 'settings' && /*#__PURE__*/React.createElement(SettingsScreen, {
    key: `set-${dataKey}`,
    tweaks: tweaks,
    onBack: () => setRoute('accounts'),
    onDataChanged: reloadData,
    onOpenGlobalModal: setGlobalModal
  }), globalModal && /*#__PURE__*/React.createElement(ModalOverlay, {
    onClose: () => setGlobalModal(null)
  }, globalModal === 'refresh_all' && /*#__PURE__*/React.createElement(RefreshAllModal, {
    key: 'refresh-all',
    accent: tweaks.accent,
    onClose: () => setGlobalModal(null),
    onDataChanged: reloadData
  }), globalModal === 'schedule' && /*#__PURE__*/React.createElement(ScheduleModal, {
    accent: tweaks.accent,
    onDataChanged: reloadData,
    onClose: () => setGlobalModal(null)
  }), globalModal === 'add_list' && /*#__PURE__*/React.createElement(AddListModal, {
    accent: tweaks.accent,
    onDataChanged: reloadData,
    onClose: () => setGlobalModal(null)
  }), globalModal === 'add_one' && /*#__PURE__*/React.createElement(AddOneInline, {
    accent: tweaks.accent,
    onDataChanged: reloadData,
    onClose: () => setGlobalModal(null)
  })), route !== 'tv' && route !== 'account_detail' && /*#__PURE__*/React.createElement(RouteFloater, {
    route: route,
    setRoute: setRoute,
    routes: ROUTES,
    accent: tweaks.accent
  }), !_isEmbedMode() && /*#__PURE__*/React.createElement(TweaksPanel, {
    title: "Tweaks"
  }, /*#__PURE__*/React.createElement(TweakSection, {
    title: "\u0414\u0430\u043D\u043D\u044B\u0435"
  }, /*#__PURE__*/React.createElement(TweakButton, {
    label: reloading ? 'Обновление…' : 'Перезагрузить данные',
    onClick: () => {
      void reloadData();
    }
  })), /*#__PURE__*/React.createElement(TweakSection, {
    title: "\u0421\u0442\u0430\u0440\u0442 + \u043D\u0430\u0432\u0438\u0433\u0430\u0446\u0438\u044F"
  }, /*#__PURE__*/React.createElement(TweakSelect, {
    label: "\u042D\u043A\u0440\u0430\u043D",
    value: route,
    onChange: v => setRoute(v),
    options: ROUTES.map(r => ({
      value: r.id,
      label: r.label
    }))
  })), /*#__PURE__*/React.createElement(TweakSection, {
    title: "TV-\u0440\u0435\u0436\u0438\u043C"
  }, /*#__PURE__*/React.createElement(TweakRadio, {
    label: "\u041D\u0430\u0441\u0442\u0440\u043E\u0435\u043D\u0438\u0435",
    value: tweaks.tv_mood,
    onChange: v => setTweak('tv_mood', v),
    options: [{
      value: 'mission',
      label: 'Mission'
    }, {
      value: 'bloomberg',
      label: 'Bloom'
    }, {
      value: 'calm',
      label: 'Calm'
    }]
  })), /*#__PURE__*/React.createElement(TweakSection, {
    title: "\u0410\u043A\u0446\u0435\u043D\u0442"
  }, /*#__PURE__*/React.createElement(TweakColor, {
    label: "\u0426\u0432\u0435\u0442",
    value: tweaks.accent,
    onChange: v => setTweak('accent', v),
    options: ['#6aa9ff', '#4ade80', '#f59e0b', '#ec4899', '#ffffff']
  })), /*#__PURE__*/React.createElement(TweakSection, {
    title: "\u0421\u043F\u0438\u0441\u043E\u043A \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u043E\u0432"
  }, /*#__PURE__*/React.createElement(TweakRadio, {
    label: "\u0412\u0438\u0434",
    value: tweaks.accounts_view,
    onChange: v => setTweak('accounts_view', v),
    options: [{
      value: 'table',
      label: 'Таблица'
    }, {
      value: 'cards',
      label: 'Карточки'
    }]
  }))), /*#__PURE__*/React.createElement(NFUiHost, null), /*#__PURE__*/React.createElement(MobileGlobalStyle, null));
}
function RouteFloater({
  route,
  setRoute,
  routes,
  accent
}) {
  const isMobile = useIsMobile(980);
  const embed = _isEmbedMode();
  const navRoutes = routes.filter(r => r.id !== 'account_detail');
  const mobileLabel = (id, label) => {
    if (!isMobile) return label;
    if (id === 'tv') return 'TV';
    if (id === 'accounts') return 'Акк';
    if (id === 'analytics') return 'Аналитика';
    if (id === 'settings') return 'Настр';
    return label;
  };
  return /*#__PURE__*/React.createElement(React.Fragment, null, isMobile && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      left: 0,
      right: 0,
      bottom: 0,
      height: 78,
      background: 'linear-gradient(180deg, rgba(5,7,11,0), rgba(5,7,11,0.96) 42%, rgba(5,7,11,1) 100%)',
      zIndex: 88,
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      bottom: embed ? isMobile ? 6 : 12 : isMobile ? 8 : 24,
      left: isMobile ? 8 : '50%',
      right: isMobile ? 8 : 'auto',
      transform: isMobile ? 'none' : 'translateX(-50%)',
      display: 'flex',
      gap: 4,
      padding: 6,
      borderRadius: 999,
      background: isMobile ? 'rgba(10,12,18,0.96)' : 'rgba(10,12,18,0.85)',
      backdropFilter: 'blur(16px)',
      border: '1px solid var(--line-2)',
      zIndex: 90,
      boxShadow: '0 8px 30px rgba(0,0,0,0.5)'
    }
  }, navRoutes.map(r => /*#__PURE__*/React.createElement("button", {
    key: r.id,
    onClick: () => setRoute(r.id),
    style: {
      flex: isMobile ? 1 : 'unset',
      minWidth: 0,
      padding: isMobile ? '9px 8px' : '9px 16px',
      borderRadius: 999,
      border: 'none',
      cursor: 'pointer',
      background: route === r.id ? accent : 'transparent',
      color: route === r.id ? '#000' : 'var(--ink-dim)',
      fontSize: isMobile ? 11 : 12,
      fontWeight: route === r.id ? 600 : 500,
      letterSpacing: '0.02em',
      fontFamily: 'inherit',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, mobileLabel(r.id, r.label)))));
}
try {
  if (typeof React === 'undefined' || typeof ReactDOM === 'undefined' || typeof Babel === 'undefined') {
    throw new Error('React / ReactDOM / Babel не загрузились (папка new_frontend/vendor/)');
  }
  window.__nfAppMounted = true;
  ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));
} catch (bootErr) {
  window.__nfBootError(bootErr && bootErr.message ? bootErr.message : String(bootErr));
  console.error('[new_frontend] boot failed', bootErr);
}