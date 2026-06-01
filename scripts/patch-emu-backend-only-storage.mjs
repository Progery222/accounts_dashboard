/**
 * Emu settings: server is the only source of truth (localStorage only one-time migration).
 */
import fs from 'node:fs';

const path = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(path, 'utf8');

const oldBlockStart = 'async function _emuFetchConfigFromServer(){';
const oldBlockEnd = 'function _emuFinalizeConfigForSave(cfg){';
const i = s.indexOf(oldBlockStart);
const j = s.indexOf(oldBlockEnd);
if (i < 0 || j < 0 || j <= i) throw new Error('emu server block boundaries not found');

const newBlock = `async function _emuFetchConfigFromServer(){try{const r=await _fetchJsonSoft(NF_EMU_SERVER_CONFIG_PATH);if(r.ok&&r.data&&r.data.config&&typeof r.data.config==='object')return r.data.config;}catch(_){}return null;}async function _emuPushConfigToServer(cfg){try{await _postJson(NF_EMU_SERVER_CONFIG_PATH,{config:cfg});return true;}catch(_){return false;}}function _emuApplyLoadedConfig(parsed){const merged=_emuMergeConfig(_emuDefaultConfig(),parsed);const migrated=_emuMigrateTopLeaders(merged);NF_EMU_SERVER_CONFIG_CACHE=migrated;return migrated;}async function _emuMigrateLegacyLocalStorageToServer(){try{if(await _emuFetchConfigFromServer())return;const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw||raw.length<80)return;const parsed=JSON.parse(raw);if(!parsed||typeof parsed!=='object')return;const toSave=_emuFinalizeConfigForSave(_emuApplyLoadedConfig(parsed));if(await _emuPushConfigToServer(toSave))try{window.localStorage.removeItem(NF_EMU_STORAGE_KEY);}catch(_){}}catch(_){}}function _emuLoadConfig(){return NF_EMU_SERVER_CONFIG_CACHE||_emuDefaultConfig();}async function _emuLoadConfigAsync(){const remote=await _emuFetchConfigFromServer();if(remote)return _emuApplyLoadedConfig(remote);await _emuMigrateLegacyLocalStorageToServer();const again=await _emuFetchConfigFromServer();if(again)return _emuApplyLoadedConfig(again);return _emuDefaultConfig();}function _emuSaveConfig(cfg){const next=_emuFinalizeConfigForSave(cfg||NF_EMU_SERVER_CONFIG_CACHE||_emuDefaultConfig());NF_EMU_SERVER_CONFIG_CACHE=next;return _emuPushConfigToServer(next);}`;

if (!s.includes('return NF_EMU_SERVER_CONFIG_CACHE||_emuDefaultConfig()')) {
  s = s.slice(0, i) + newBlock + s.slice(j);
}

s = s.replace(
  'void _emuEnsureServerConfigSeeded();LOAD_STATE={hasError:false,errorMessage:\'\'};',
  'LOAD_STATE={hasError:false,errorMessage:\'\'};',
);

const saveOld =
  "const save=()=>{void(async()=>{const next=_emuFinalizeConfigForSave(cfg);setCfg(next);const ok=await _emuPushConfigToServer(next);if(ok){_emuSaveConfig(next);}else{try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(next));}catch(_){}NF_EMU_SERVER_CONFIG_CACHE=next;}if(NF_EMU_RUNTIME){_emuSyncRuntimeFromConfig(NF_EMU_RUNTIME,next);if(NF_EMU_ACTIVE)_emuApplyToGlobals(NF_EMU_RUNTIME);}setSaved(ok?'Сохранено':'Сохранено только на этом устройстве (сервер недоступен)');window.setTimeout(()=>setSaved(''),ok?2000:4500);})();};";
const saveNew =
  "const save=()=>{void(async()=>{const next=_emuFinalizeConfigForSave(cfg);setCfg(next);const ok=await _emuPushConfigToServer(next);if(ok)NF_EMU_SERVER_CONFIG_CACHE=next;if(NF_EMU_RUNTIME){_emuSyncRuntimeFromConfig(NF_EMU_RUNTIME,next);if(NF_EMU_ACTIVE)_emuApplyToGlobals(NF_EMU_RUNTIME);}setSaved(ok?'Сохранено на сервере':'Ошибка: не удалось сохранить на сервере');window.setTimeout(()=>setSaved(''),ok?2000:5000);})();};";
if (s.includes(saveOld)) s = s.replace(saveOld, saveNew);

const importOld =
  'const merged=_emuFinalizeConfigForSave(_emuMergeConfig(_emuMergeConfig(_emuDefaultConfig(),cfg),patch));setCfg(merged);const ok=await _emuPushConfigToServer(merged);if(ok)_emuSaveConfig(merged);else{try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(merged));}catch(_){}NF_EMU_SERVER_CONFIG_CACHE=merged;}setSaved(ok?\'CSV импортирован\':\'CSV импортирован локально (сервер недоступен)\');';
const importNew =
  'const merged=_emuFinalizeConfigForSave(_emuMergeConfig(_emuMergeConfig(_emuDefaultConfig(),cfg),patch));setCfg(merged);const ok=await _emuPushConfigToServer(merged);if(ok)NF_EMU_SERVER_CONFIG_CACHE=merged;if(NF_EMU_RUNTIME){_emuSyncRuntimeFromConfig(NF_EMU_RUNTIME,merged);if(NF_EMU_ACTIVE)_emuApplyToGlobals(NF_EMU_RUNTIME);}setSaved(ok?\'CSV импортирован на сервер\':\'Ошибка: CSV не сохранён на сервер\');';
if (s.includes(importOld)) s = s.replace(importOld, importNew);

const resetOld =
  "const d=_emuPatchConfigFromDashboard(_emuDefaultConfig());setCfg(d);_emuSaveConfig(d);setSaved('Сброшено');";
const resetNew =
  "const d=_emuFinalizeConfigForSave(_emuPatchConfigFromDashboard(_emuDefaultConfig()));setCfg(d);const ok=await _emuSaveConfig(d);setSaved(ok?'Сброшено на сервере':'Сброс локально (сервер недоступен)');";
if (s.includes(resetOld)) s = s.replace(resetOld, resetNew);

fs.writeFileSync(path, s, 'utf8');
console.log('patched', path);
