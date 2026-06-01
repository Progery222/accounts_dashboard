/**
 * Sync TV emu settings via server API (shared across TV / PC browsers).
 */
import fs from 'node:fs';

const path = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(path, 'utf8');

const keyOld = "const NF_EMU_STORAGE_KEY='nf_tv_broadcast_emu_v1';";
const keyNew =
  "const NF_EMU_STORAGE_KEY='nf_tv_broadcast_emu_v1';const NF_EMU_SERVER_CONFIG_PATH='/api/accounts/tv-emu-config/';let NF_EMU_SERVER_CONFIG_CACHE=null;";

if (!s.includes('NF_EMU_SERVER_CONFIG_PATH')) {
  if (!s.includes(keyOld)) throw new Error('NF_EMU_STORAGE_KEY not found');
  s = s.replace(keyOld, keyNew);
}

const serverFns =
  'async function _emuFetchConfigFromServer(){try{const r=await _fetchJsonSoft(NF_EMU_SERVER_CONFIG_PATH);if(r.ok&&r.data&&r.data.config&&typeof r.data.config===\'object\')return r.data.config;}catch(_){}return null;}async function _emuPushConfigToServer(cfg){try{await _postJson(NF_EMU_SERVER_CONFIG_PATH,{config:cfg});return true;}catch(_){return false;}}async function _emuEnsureServerConfigSeeded(){const remote=await _emuFetchConfigFromServer();if(remote)return;try{const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw)return;const parsed=JSON.parse(raw);if(parsed&&typeof parsed===\'object\')await _emuPushConfigToServer(parsed);}catch(_){}}function _emuApplyLoadedConfig(parsed){const merged=_emuMergeConfig(_emuDefaultConfig(),parsed);const migrated=_emuMigrateTopLeaders(merged);NF_EMU_SERVER_CONFIG_CACHE=migrated;try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(migrated));}catch(_){}return migrated;}async function _emuLoadConfigAsync(){const remote=await _emuFetchConfigFromServer();if(remote)return _emuApplyLoadedConfig(remote);return _emuLoadConfig();}';

if (!s.includes('_emuLoadConfigAsync')) {
  const anchor = 'function _emuLoadConfig(){';
  if (!s.includes(anchor)) throw new Error('_emuLoadConfig not found');
  s = s.replace(anchor, serverFns + anchor);
}

const loadBodyOld =
  'function _emuLoadConfig(){try{const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw)return _emuDefaultConfig();const parsed=JSON.parse(raw);const merged=_emuMergeConfig(_emuDefaultConfig(),parsed);const migrated=_emuMigrateTopLeaders(merged);const before=JSON.stringify(merged.top?.leadersViews||[]);const after=JSON.stringify(migrated.top?.leadersViews||[]);if(before!==after){try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(migrated));}catch(_){}}return migrated;}catch(_){return _emuDefaultConfig();}}';
const loadBodyNew =
  'function _emuLoadConfig(){if(NF_EMU_SERVER_CONFIG_CACHE)return NF_EMU_SERVER_CONFIG_CACHE;try{const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw)return _emuDefaultConfig();return _emuApplyLoadedConfig(JSON.parse(raw));}catch(_){return _emuDefaultConfig();}}';

if (!s.includes('if(NF_EMU_SERVER_CONFIG_CACHE)return NF_EMU_SERVER_CONFIG_CACHE')) {
  if (!s.includes(loadBodyOld)) throw new Error('_emuLoadConfig body not found');
  s = s.replace(loadBodyOld, loadBodyNew);
}

const saveOld = 'function _emuSaveConfig(cfg){window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(cfg));}';
const saveNew =
  'function _emuSaveConfig(cfg){NF_EMU_SERVER_CONFIG_CACHE=cfg;try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(cfg));}catch(_){}void _emuPushConfigToServer(cfg);}';

if (!s.includes('void _emuPushConfigToServer(cfg)')) {
  if (!s.includes(saveOld)) throw new Error('_emuSaveConfig not found');
  s = s.replace(saveOld, saveNew);
}

const dashOld = '}async function loadDashboardData(){LOAD_STATE={hasError:false,errorMessage:\'\'};';
const dashNew =
  '}async function loadDashboardData(){void _emuEnsureServerConfigSeeded();LOAD_STATE={hasError:false,errorMessage:\'\'};';

if (!s.includes('void _emuEnsureServerConfigSeeded();LOAD_STATE')) {
  if (!s.includes(dashOld)) throw new Error('loadDashboardData not found');
  s = s.replace(dashOld, dashNew);
}

const settingsInitRe =
  /const\[cfg,setCfg\]=React\.useState\(\(\)=>\{const loaded=_emuHydrateConfigLeaders\(_emuLoadConfig\(\)\);\/\/ If user has not customized emulation yet, populate TOP defaults from dashboard\.\s*const leaders=loaded\?\.top\?\.leaders\|\|\[\];const profiles=loaded\?\.top\?\.profiles\|\|\[\];const isDefaultLike=profiles\.some\(p=>String\(p\?\.id\|\|''\)==='p1'\|\|String\(p\?\.label\|\|''\)==='Профиль A'\);return loaded;\}\);const\[saved,setSaved\]=React\.useState\(''\);/;
const settingsInitNew =
  "const[cfg,setCfg]=React.useState(()=>_emuHydrateConfigLeaders(_emuDefaultConfig()));const[cfgLoading,setCfgLoading]=React.useState(true);const[saved,setSaved]=React.useState('');";

if (!s.includes('const[cfgLoading,setCfgLoading]')) {
  if (!settingsInitRe.test(s)) throw new Error('EmuSettings init not found');
  s = s.replace(settingsInitRe, settingsInitNew);
}

const settingsFxOld =
  'const[saved,setSaved]=React.useState(\'\');const[paused,setPaused]=React.useState(()=>!!NF_EMU_PAUSED);React.useEffect(()=>{let cancelled=false;if(!NF_EMU_DASHBOARD_ACCOUNTS?.length';
const settingsFxNew =
  'const[saved,setSaved]=React.useState(\'\');const[paused,setPaused]=React.useState(()=>!!NF_EMU_PAUSED);React.useEffect(()=>{let cancelled=false;void _emuLoadConfigAsync().then(loaded=>{if(cancelled)return;setCfg(_emuHydrateConfigLeaders(loaded));setCfgLoading(false);}).catch(()=>{if(!cancelled)setCfgLoading(false);});return()=>{cancelled=true;};},[]);React.useEffect(()=>{let cancelled=false;if(!NF_EMU_DASHBOARD_ACCOUNTS?.length';

if (!s.includes('void _emuLoadConfigAsync().then(loaded=>')) {
  if (!s.includes(settingsFxOld)) throw new Error('EmuSettings effects anchor not found');
  s = s.replace(settingsFxOld, settingsFxNew);
}

const saveFnOld =
  'const save=()=>{const next=_emuFinalizeConfigForSave(cfg);_emuSaveConfig(next);setCfg(next);if(NF_EMU_RUNTIME){_emuSyncRuntimeFromConfig(NF_EMU_RUNTIME,next);if(NF_EMU_ACTIVE)_emuApplyToGlobals(NF_EMU_RUNTIME);}setSaved(\'Сохранено\');window.setTimeout(()=>setSaved(\'\'),2000);};';
const saveFnNew =
  'const save=()=>{void(async()=>{const next=_emuFinalizeConfigForSave(cfg);setCfg(next);const ok=await _emuPushConfigToServer(next);if(ok){_emuSaveConfig(next);}else{try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(next));}catch(_){}NF_EMU_SERVER_CONFIG_CACHE=next;}if(NF_EMU_RUNTIME){_emuSyncRuntimeFromConfig(NF_EMU_RUNTIME,next);if(NF_EMU_ACTIVE)_emuApplyToGlobals(NF_EMU_RUNTIME);}setSaved(ok?\'Сохранено\':\'Сохранено только на этом устройстве (сервер недоступен)\');window.setTimeout(()=>setSaved(\'\'),ok?2000:4500);})();};';

if (!s.includes('await _emuPushConfigToServer(next)')) {
  if (!s.includes(saveFnOld)) throw new Error('EmuSettings save not found');
  s = s.replace(saveFnOld, saveFnNew);
}

const importSaveOld =
  'const merged=_emuFinalizeConfigForSave(_emuMergeConfig(_emuMergeConfig(_emuDefaultConfig(),cfg),patch));setCfg(merged);_emuSaveConfig(merged);setSaved(\'CSV импортирован\');';
const importSaveNew =
  'const merged=_emuFinalizeConfigForSave(_emuMergeConfig(_emuMergeConfig(_emuDefaultConfig(),cfg),patch));setCfg(merged);const ok=await _emuPushConfigToServer(merged);if(ok)_emuSaveConfig(merged);else{try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(merged));}catch(_){}NF_EMU_SERVER_CONFIG_CACHE=merged;}setSaved(ok?\'CSV импортирован\':\'CSV импортирован локально (сервер недоступен)\');';

if (!s.includes('CSV импортирован локально')) {
  if (!s.includes(importSaveOld)) throw new Error('CSV import save not found');
  s = s.replace(importSaveOld, importSaveNew);
}

const emuScreenOld =
  'function EmuBroadcastScreen({tweaks}){const[,setTick]=React.useState(0);React.useEffect(()=>{NF_EMU_ACTIVE=true;let cancelled=false;const rt=_emuRestart();setTick(n=>n+1);const _tc=rt?.cfg?.top||_emuLoadConfig().top;';
const emuScreenNew =
  'function EmuBroadcastScreen({tweaks}){const[,setTick]=React.useState(0);React.useEffect(()=>{NF_EMU_ACTIVE=true;let cancelled=false;let rt=null;void _emuLoadConfigAsync().then(cfg=>{if(cancelled)return;rt=_emuRestart(cfg);setTick(n=>n+1);const _tc=rt?.cfg?.top||cfg.top;';

if (!s.includes('void _emuLoadConfigAsync().then(cfg=>{if(cancelled)return;rt=_emuRestart(cfg)')) {
  if (!s.includes(emuScreenOld)) throw new Error('EmuBroadcastScreen not found');
  s = s.replace(emuScreenOld, emuScreenNew);
}

// Close the async .then before interval — find the prefetch chain end
const emuPrefetchOld =
  'void _emuPrefetchLeaderAvatars(leadersForPrefetch).then(()=>{if(cancelled||!NF_EMU_RUNTIME)return;const avatarsRefreshed=_emuRefreshDashboardAccountAvatars();const leadersSynced=_emuSyncRuntimeLeaderAvatars(NF_EMU_RUNTIME);if(avatarsRefreshed||leadersSynced){_emuApplyToGlobals(NF_EMU_RUNTIME);setTick(n=>n+1);}});const id=window.setInterval(()=>{if(!NF_EMU_RUNTIME)return;';
const emuPrefetchNew =
  'void _emuPrefetchLeaderAvatars(leadersForPrefetch).then(()=>{if(cancelled||!NF_EMU_RUNTIME)return;const avatarsRefreshed=_emuRefreshDashboardAccountAvatars();const leadersSynced=_emuSyncRuntimeLeaderAvatars(NF_EMU_RUNTIME);if(avatarsRefreshed||leadersSynced){_emuApplyToGlobals(NF_EMU_RUNTIME);setTick(n=>n+1);}});});const id=window.setInterval(()=>{if(!NF_EMU_RUNTIME)return;';

if (!s.includes('}});});const id=window.setInterval(()=>{if(!NF_EMU_RUNTIME)return;')) {
  if (!s.includes(emuPrefetchOld)) throw new Error('EmuBroadcast prefetch block not found');
  s = s.replace(emuPrefetchOld, emuPrefetchNew);
}

fs.writeFileSync(path, s, 'utf8');
console.log('patched', path);
