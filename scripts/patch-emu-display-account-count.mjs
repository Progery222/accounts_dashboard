import fs from 'node:fs';
import path from 'node:path';

const bundlePath = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(bundlePath, 'utf8');

if (!s.includes('function _emuDisplayAccountCount')) {
  const anchor = 'function _emuApplyToGlobals(rt){';
  const helper =
    'function _emuDisplayAccountCount(cfg){const n=Number(cfg?.displayAccountCount);return Number.isFinite(n)&&n>=0?Math.round(n):NF_EMU_DISPLAY_ACCOUNT_COUNT;}';
  if (!s.includes(anchor)) throw new Error('_emuApplyToGlobals not found');
  s = s.replace(anchor, helper + anchor);
}

s = s.replace(
  'const NF_EMU_DISPLAY_ACCOUNT_COUNT=1000;',
  'const NF_EMU_DISPLAY_ACCOUNT_COUNT=239;',
);

if (!s.includes('displayAccountCount:239,atom:')) {
  s = s.replace(
    'return{version:2,atom:{followers:',
    'return{version:2,displayAccountCount:239,atom:{followers:',
  );
}

s = s.replace(
  'accounts:NF_EMU_DISPLAY_ACCOUNT_COUNT};const viewsTotal',
  'accounts:_emuDisplayAccountCount(rt.cfg)};const viewsTotal',
);

const mergeOld = '}}return out;}function _emuCap(ch){';
const mergeNew =
  '}}if(patch.displayAccountCount!=null)out.displayAccountCount=Math.max(0,Math.round(Number(patch.displayAccountCount)));return out;}function _emuCap(ch){';
if (!s.includes('patch.displayAccountCount!=null')) {
  if (!s.includes(mergeOld)) throw new Error('_emuMergeConfig tail not found');
  s = s.replace(mergeOld, mergeNew);
}

const finOld =
  'return _emuHydrateConfigLeaders({...cfg,top,pulse});}function _emuSaveConfig(cfg){';
const finNew =
  'return _emuHydrateConfigLeaders({...cfg,top,pulse,displayAccountCount:Math.max(0,Math.round(Number(cfg.displayAccountCount)||NF_EMU_DISPLAY_ACCOUNT_COUNT))});}function _emuSaveConfig(cfg){';
if (!s.includes('displayAccountCount:Math.max(0,Math.round(Number(cfg.displayAccountCount)')) {
  if (!s.includes(finOld)) throw new Error('_emuFinalizeConfigForSave not found');
  s = s.replace(finOld, finNew);
}

const uiOld =
  '/*#__PURE__*/React.createElement(EmuChannelFields,{label:"\\u041F\\u043E\\u0434\\u0440\\u043E\\u0431\\u043D\\u0435\\u0435 \\u043E \\u0433\\u0440\\u0430\\u0444\\u0438\\u043A\\u0435",size:12})),/*#__PURE__*/React.createElement(EmuChannelFields,{label:"\\u041F\\u043E\\u0434\\u043F\\u0438\\u0441\\u0447\\u0438\\u043A\\u0438"';
// wrong anchor - use followers field

const atomOld =
  '/*#__PURE__*/React.createElement(EmuChannelFields,{label:"\\u041F\\u043E\\u0434\\u043F\\u0438\\u0441\\u0447\\u0438\\u043A\\u0438",channel:cfg.atom.followers,onChange:ch=>setAtom(\'followers\',ch),showLaunchValue:true})';
const atomNew =
  '/*#__PURE__*/React.createElement("div",{style:{marginBottom:14,padding:"12px 14px",borderRadius:12,border:"1px solid var(--line)",background:"rgba(255,255,255,0.02)"}},/*#__PURE__*/React.createElement("label",{style:{fontSize:12,color:"var(--ink-dim)"}},\"\\u0410\\u043A\\u043A\\u0430\\u0443\\u043D\\u0442\\u043E\\u0432 \\u0432 \\u0448\\u0430\\u043F\\u043A\\u0435 TV (BROADCAST)\",/*#__PURE__*/React.createElement("input",{type:"number",min:"0",step:"1",value:Math.round(Number(cfg.displayAccountCount)||NF_EMU_DISPLAY_ACCOUNT_COUNT),onChange:e=>setCfg(c=>({...c,displayAccountCount:Math.max(0,Math.round(Number(e.target.value)||0))})),style:{display:"block",width:"100%",maxWidth:200,marginTop:6,padding:"10px 12px",borderRadius:8,border:"1px solid var(--line)",background:"rgba(0,0,0,0.2)",color:"var(--ink)",fontSize:16,fontWeight:600}}))),/*#__PURE__*/React.createElement(EmuChannelFields,{label:"\\u041F\\u043E\\u0434\\u043F\\u0438\\u0441\\u0447\\u0438\\u043A\\u0438",channel:cfg.atom.followers,onChange:ch=>setAtom(\'followers\',ch),showLaunchValue:true})';

if (!s.includes('displayAccountCount:Math.max(0,Math.round(Number(e.target.value)')) {
  if (!s.includes(atomOld)) throw new Error('atom tab UI anchor not found');
  s = s.replace(atomOld, atomNew);
}

fs.writeFileSync(bundlePath, s, 'utf8');
console.log('patched', bundlePath);

const cfgPath = path.join('backend', 'config', 'tv_broadcast_emu.json');
if (fs.existsSync(cfgPath)) {
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  cfg.displayAccountCount = 239;
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2), 'utf8');
  console.log('updated', cfgPath, 'displayAccountCount=239');
}
