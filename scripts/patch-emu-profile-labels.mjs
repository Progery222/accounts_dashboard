import fs from 'node:fs';
import path from 'node:path';

const bundlePath = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(bundlePath, 'utf8');

if (!s.includes('let NF_EMU_PROFILE_CATALOG')) {
  s = s.replace(
    'let NF_EMU_SERVER_CONFIG_CACHE=null;',
    'let NF_EMU_SERVER_CONFIG_CACHE=null;let NF_EMU_PROFILE_CATALOG=null;',
  );
}

if (!s.includes('function _emuProfileMeta(')) {
  const anchor = 'function _emuResolveLeaderProfile(row){';
  const helper =
    'function _emuProfileMeta(id){const p=String(id||"none");if(p==="none")return{color:"#525a70",label:"Без профиля"};if(PROFILE_META[p])return PROFILE_META[p];const cat=(NF_EMU_PROFILE_CATALOG||NF_EMU_DASHBOARD_PROFILES||[]).find(x=>String(x.id)===p);if(cat)return{color:String(cat.color||"#525a70"),label:String(cat.label||"Профиль")};const cfgList=NF_EMU_RUNTIME?.cfg?.top?.profiles||[];const em=cfgList.find(x=>String(x.id)===p);if(em)return{color:String(em.color||"#525a70"),label:String(em.label||"Профиль")};return null;}async function _emuEnsureProfileCatalog(){if(Array.isArray(NF_EMU_PROFILE_CATALOG)&&NF_EMU_PROFILE_CATALOG.length)return NF_EMU_PROFILE_CATALOG;for(const base of _apiBaseCandidates()){try{const res=await fetch(`${base}/api/accounts/profiles/?include_hidden_profiles=1`);if(!res.ok)continue;const data=await res.json();if(!Array.isArray(data))continue;NF_EMU_PROFILE_CATALOG=data.map((p,idx)=>({id:String(p.id),label:String(p.name||`Профиль ${idx+1}`),color:String(p.color||PROFILE_PALETTE[idx%PROFILE_PALETTE.length]),accounts:Number(p.account_count||0)}));NF_EMU_DASHBOARD_PROFILES=NF_EMU_PROFILE_CATALOG.slice();return NF_EMU_PROFILE_CATALOG;}catch(_){}}return NF_EMU_PROFILE_CATALOG||[];}';
  if (!s.includes(anchor)) throw new Error('_emuResolveLeaderProfile not found');
  s = s.replace(anchor, helper + anchor);
}

const resolveOld =
  "function _emuResolveLeaderProfile(row){if(!row||typeof row!=='object')return'none';const p=String(row.profile||'').trim();if(p&&p!=='none'&&(PROFILE_META[p]||PROFILES.some(pr=>String(pr.id)===p)))return p;";
const resolveNew =
  "function _emuResolveLeaderProfile(row){if(!row||typeof row!=='object')return'none';const p=String(row.profile||'').trim();if(p&&p!=='none'&&(_emuProfileMeta(p)||PROFILES.some(pr=>String(pr.id)===p)))return p;";
if (!s.includes('_emuProfileMeta(p)||PROFILES.some')) {
  if (!s.includes(resolveOld)) throw new Error('_emuResolveLeaderProfile head not found');
  s = s.replace(resolveOld, resolveNew);
}

const rowOld =
  "const prof=PROFILE_META[_profId]||(a.profile_name?{color:'#525a70',label:String(a.profile_name)}:null)||{color:'#525a70',label:'Без профиля'};";
const rowNew =
  "const prof=_emuProfileMeta(_profId)||(a.profile_name?{color:'#525a70',label:String(a.profile_name)}:null)||{color:'#525a70',label:'Без профиля'};";
if (!s.includes('const prof=_emuProfileMeta(_profId)')) {
  if (!s.includes(rowOld)) throw new Error('TvTopLeaderboardRow prof lookup not found');
  s = s.replace(rowOld, rowNew);
}

const loadProfilesOld =
  "const profilesResp=profilesR.ok?profilesR.data:null;if(Array.isArray(profilesResp)&&!NF_EMU_ACTIVE){hadAnySuccess=true;PROFILES=[{id:'none',label:'Без профиля',color:'#525a70',accounts:0},...profilesResp.map((p,idx)=>({id:String(p.id),label:String(p.name||`Профиль ${idx+1}`),color:String(p.color||PROFILE_PALETTE[idx%PROFILE_PALETTE.length]),accounts:Number(p.account_count||0)}))];}";
const loadProfilesNew =
  "const profilesResp=profilesR.ok?profilesR.data:null;if(Array.isArray(profilesResp)){NF_EMU_PROFILE_CATALOG=profilesResp.map((p,idx)=>({id:String(p.id),label:String(p.name||`Профиль ${idx+1}`),color:String(p.color||PROFILE_PALETTE[idx%PROFILE_PALETTE.length]),accounts:Number(p.account_count||0)}));NF_EMU_DASHBOARD_PROFILES=NF_EMU_PROFILE_CATALOG.slice();if(!NF_EMU_ACTIVE){hadAnySuccess=true;PROFILES=[{id:'none',label:'Без профиля',color:'#525a70',accounts:0},...NF_EMU_PROFILE_CATALOG];}}";
if (!s.includes('NF_EMU_PROFILE_CATALOG=profilesResp.map')) {
  if (!s.includes(loadProfilesOld)) throw new Error('loadAppData profiles block not found');
  s = s.replace(loadProfilesOld, loadProfilesNew);
}

const applyProfilesOld =
  'PROFILES=(rt.top.profiles||[]).map(p=>{const id=String(p.meta?.id??\'none\');const dash=dashProfiles.find(dp=>String(dp.id)===id);const emuN=emuCounts.get(id);const accN=byProfile.get(id);return{id,label:String(p.meta?.label??dash?.label??\'Без профиля\'),color:String(p.meta?.color??dash?.color??\'#525a70\'),accounts:Math.round(p.accounts?.value??emuN??0)};});';
const applyProfilesNew =
  'const _emuProfTpl=new Map((rt.top.profiles||[]).map(p=>[String(p.meta?.id??\'none\'),p]));const _emuProfIds=new Set([..._emuProfTpl.keys(),...(NF_EMU_PROFILE_CATALOG||NF_EMU_DASHBOARD_PROFILES||dashProfiles||[]).map(p=>String(p.id)),...rt.top.leaders.map(l=>String(l.row?.profile||\'none\')).filter(x=>x&&x!==\'none\')]);PROFILES=[..._emuProfIds].filter(id=>id&&id!==\'none\').map(id=>{const tpl=_emuProfTpl.get(id);const dash=(NF_EMU_PROFILE_CATALOG||NF_EMU_DASHBOARD_PROFILES||dashProfiles||[]).find(dp=>String(dp.id)===id);const emuN=emuCounts.get(id);const accN=byProfile.get(id);return{id,label:String(tpl?.meta?.label??dash?.label??\'Без профиля\'),color:String(tpl?.meta?.color??dash?.color??\'#525a70\'),accounts:Math.round(tpl?.accounts?.value??emuN??accN??dash?.accounts??0)};});';
if (!s.includes('_emuProfIds=new Set')) {
  if (!s.includes(applyProfilesOld)) throw new Error('_emuApplyToGlobals PROFILES block not found');
  s = s.replace(applyProfilesOld, applyProfilesNew);
}

const bootOld =
  'void _emuLoadConfigAsync().then(cfg=>{if(cancelled)return;rt=_emuRestart(cfg);';
const bootNew =
  'void _emuLoadConfigAsync().then(async cfg=>{if(cancelled)return;await _emuEnsureProfileCatalog();if(cancelled)return;rt=_emuRestart(cfg);';
if (!s.includes('await _emuEnsureProfileCatalog()')) {
  if (!s.includes(bootOld)) throw new Error('emu boot block not found');
  s = s.replace(bootOld, bootNew);
}

fs.writeFileSync(bundlePath, s, 'utf8');
console.log('patched', bundlePath);

const cfgPath = path.join('backend', 'config', 'tv_broadcast_emu.json');
if (fs.existsSync(cfgPath)) {
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const top = cfg.top || {};
  const existing = Array.isArray(top.profiles) ? top.profiles : [];
  const byId = new Map(existing.map((p) => [String(p.id), p]));
  const leaders = [
    ...(top.leadersViews || []),
    ...(top.leadersClicks || []),
    ...(top.leaders || []),
  ];
  const defaults = {
    '4': { id: '4', label: 'Фил', color: '#22c55e' },
    '6': { id: '6', label: 'Музыка', color: '#ec4899' },
    '7': { id: '7', label: 'Спорт Завод', color: '#f97316' },
  };
  for (const row of leaders) {
    const pid = String(row.profile || '').trim();
    if (!pid || pid === 'none' || byId.has(pid)) continue;
    const d = defaults[pid] || { id: pid, label: `Профиль ${pid}`, color: '#525a70' };
    byId.set(pid, {
      ...d,
      accounts: {
        start: 0,
        stepMin: 0,
        stepMax: 0,
        intervalMinSec: 60000,
        intervalMaxSec: 60000,
        max: 200,
        launchValue: 0,
        sparkRebuildSec: 0,
        seedDeltaMin: 0,
        seedDeltaMax: 0,
      },
    });
  }
  top.profiles = [...byId.values()];
  cfg.top = top;
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2), 'utf8');
  console.log('updated', cfgPath, 'profiles:', top.profiles.map((p) => p.id).join(', '));
}
