import fs from 'node:fs';

const path = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(path, 'utf8');

const finalizeFn =
  'function _emuFinalizeConfigForSave(cfg){if(!cfg||typeof cfg!==\'object\')return _emuDefaultConfig();const top={...cfg.top};if(Array.isArray(top.leadersViews)&&top.leadersViews.length){top.leaders=top.leadersViews.map(r=>({...r}));}const pulse={...cfg.pulse,viewsChart:_emuNormalizePulseChart(cfg.pulse?.viewsChart)};return _emuHydrateConfigLeaders({...cfg,top,pulse});}';
if (!s.includes('_emuFinalizeConfigForSave')) {
  const anchor = 'function _emuSaveConfig(cfg){';
  if (!s.includes(anchor)) throw new Error('_emuSaveConfig not found');
  s = s.replace(anchor, finalizeFn + anchor);
}

const initOld =
  'return isDefaultLike?_emuPatchConfigFromDashboard(loaded,{syncProfileCounts:true,syncLeaderAccounts:false}):loaded;});const[saved,setSaved]';
const initNew = 'return loaded;});const[saved,setSaved]';
if (s.includes(initOld)) {
  s = s.replace(initOld, initNew);
}

const saveOld =
  "const save=()=>{const next=_emuHydrateConfigLeaders({...cfg,pulse:{...cfg.pulse,viewsChart:_emuNormalizePulseChart(cfg.pulse?.viewsChart)}});_emuSaveConfig(next);";
const saveNew =
  'const save=()=>{const next=_emuFinalizeConfigForSave(cfg);_emuSaveConfig(next);';
if (s.includes(saveOld)) {
  s = s.replace(saveOld, saveNew);
}

const importOld =
  'const merged=_emuHydrateConfigLeaders(_emuMergeConfig(_emuDefaultConfig(),patch));setCfg(merged);_emuSaveConfig(merged);';
const importNew =
  'const merged=_emuFinalizeConfigForSave(_emuMergeConfig(_emuMergeConfig(_emuDefaultConfig(),cfg),patch));setCfg(merged);_emuSaveConfig(merged);';
if (s.includes(importOld)) {
  s = s.replace(importOld, importNew);
}

const exportOld = 'const exportCsv=()=>{const next=_emuPrepareConfigForCsv(cfg);_emuDownloadConfigCsv(next);';
const exportNew =
  'const exportCsv=()=>{const next=_emuFinalizeConfigForSave(_emuMergeConfig(_emuDefaultConfig(),cfg));_emuDownloadConfigCsv(next);';
if (s.includes(exportOld)) {
  s = s.replace(exportOld, exportNew);
}

const restartOld =
  'const next=_emuHydrateConfigLeaders(cfg);_emuSaveConfig(next);setCfg(next);if(NF_EMU_RUNTIME||NF_EMU_ACTIVE){_emuRestart(next);';
const restartNew =
  'const next=_emuFinalizeConfigForSave(cfg);_emuSaveConfig(next);setCfg(next);if(NF_EMU_RUNTIME||NF_EMU_ACTIVE){_emuRestart(next);';
if (s.includes(restartOld)) {
  s = s.replace(restartOld, restartNew);
}

// CSV export: leadersViews + leadersClicks
const csvExportOld =
  "for(const row of cfg?.top?.leaders||[]){const uname=String(row?.username||row?.id||'leader').trim().toLowerCase()||'leader';const base=`leader.${uname}`;for(const f of['name','username','platform','profile','avatarUrl','viewsStart','clicksStart']){if(row[f]!=null&&row[f]!=='')rows.push(['top',base,f,row[f]]);}_emuCsvPushChannel(rows,'top',`${base}.dViews`,row.dViews);_emuCsvPushChannel(rows,'top',`${base}.dClicks`,row.dClicks);}";
const csvExportNew =
  "const _emuCsvPushLeaderRow=(rows,kind,row)=>{const uname=String(row?.username||row?.id||'leader').trim().toLowerCase()||'leader';const base=`leader.${kind}.${uname}`;for(const f of['name','username','platform','profile','avatarUrl','viewsStart','clicksStart']){if(row[f]!=null&&row[f]!=='')rows.push(['top',base,f,row[f]]);}_emuCsvPushChannel(rows,'top',`${base}.dViews`,row.dViews);_emuCsvPushChannel(rows,'top',`${base}.dClicks`,row.dClicks);};for(const row of cfg?.top?.leadersViews||cfg?.top?.leaders||[])_emuCsvPushLeaderRow(rows,'views',row);for(const row of cfg?.top?.leadersClicks||[])_emuCsvPushLeaderRow(rows,'clicks',row);";
if (!s.includes('_emuCsvPushLeaderRow')) {
  if (!s.includes(csvExportOld)) throw new Error('CSV export leaders block not found');
  s = s.replace(csvExportOld, csvExportNew);
}

// CSV import: leader.views.* / leader.clicks.*
const csvPatchInitOld =
  "const patch={version:2,atom:{},pulse:{platform:{}},top:{leaders:[],profiles:[],platformAccounts:{},platformClicks:{}}};const leadersByKey=new Map();";
const csvPatchInitNew =
  "const patch={version:2,atom:{},pulse:{platform:{}},top:{leaders:[],leadersViews:[],leadersClicks:[],profiles:[],platformAccounts:{},platformClicks:{}}};const leadersByKey=new Map();const leadersViewsByKey=new Map();const leadersClicksByKey=new Map();const ensureLeaderViews=key=>{const k=String(key||'leader').trim().toLowerCase()||'leader';if(!leadersViewsByKey.has(k)){leadersViewsByKey.set(k,{username:k,name:k,platform:'tiktok',profile:'none',avatarUrl:'',viewsStart:0,clicksStart:0,dViews:{},dClicks:{}});}return leadersViewsByKey.get(k);};const ensureLeaderClicks=key=>{const k=String(key||'leader').trim().toLowerCase()||'leader';if(!leadersClicksByKey.has(k)){leadersClicksByKey.set(k,{username:k,name:k,platform:'tiktok',profile:'none',avatarUrl:'',viewsStart:0,clicksStart:0,dViews:{},dClicks:{}});}return leadersClicksByKey.get(k);};";
if (!s.includes('leadersViewsByKey')) {
  if (!s.includes(csvPatchInitOld)) throw new Error('CSV import patch init not found');
  s = s.replace(csvPatchInitOld, csvPatchInitNew);
}

const csvLeaderBlockOld =
  "if(path.startsWith('leader.')){const rest=path.slice('leader.'.length);const dot=rest.indexOf('.');const leaderKey=(dot>=0?rest.slice(0,dot):rest).trim().toLowerCase();const sub=dot>=0?rest.slice(dot+1):'';const L=ensureLeader(leaderKey);if(sub==='dViews'||sub==='dClicks'){if(!L[sub])L[sub]={};_emuCsvSetField(L[sub],field,value);}else{_emuCsvSetField(L,field,value);}continue;}";
const csvLeaderBlockNew =
  "if(path.startsWith('leader.views.')){const rest=path.slice('leader.views.'.length);const dot=rest.indexOf('.');const leaderKey=(dot>=0?rest.slice(0,dot):rest).trim().toLowerCase();const sub=dot>=0?rest.slice(dot+1):'';const L=ensureLeaderViews(leaderKey);if(sub==='dViews'||sub==='dClicks'){if(!L[sub])L[sub]={};_emuCsvSetField(L[sub],field,value);}else{_emuCsvSetField(L,field,value);}continue;}if(path.startsWith('leader.clicks.')){const rest=path.slice('leader.clicks.'.length);const dot=rest.indexOf('.');const leaderKey=(dot>=0?rest.slice(0,dot):rest).trim().toLowerCase();const sub=dot>=0?rest.slice(dot+1):'';const L=ensureLeaderClicks(leaderKey);if(sub==='dViews'||sub==='dClicks'){if(!L[sub])L[sub]={};_emuCsvSetField(L[sub],field,value);}else{_emuCsvSetField(L,field,value);}continue;}if(path.startsWith('leader.')){const rest=path.slice('leader.'.length);const dot=rest.indexOf('.');const leaderKey=(dot>=0?rest.slice(0,dot):rest).trim().toLowerCase();const sub=dot>=0?rest.slice(dot+1):'';const L=ensureLeader(leaderKey);if(sub==='dViews'||sub==='dClicks'){if(!L[sub])L[sub]={};_emuCsvSetField(L[sub],field,value);}else{_emuCsvSetField(L,field,value);}continue;}";
if (!s.includes("path.startsWith('leader.views.')")) {
  if (!s.includes(csvLeaderBlockOld)) throw new Error('CSV import leader block not found');
  s = s.replace(csvLeaderBlockOld, csvLeaderBlockNew);
}

const csvEndOld =
  'patch.top.leaders=Array.from(leadersByKey.values());patch.top.profiles=Array.from(profilesByKey.values());if(!patch.top.leaders.length)delete patch.top.leaders;';
const csvEndNew =
  'patch.top.leadersViews=Array.from(leadersViewsByKey.values());patch.top.leadersClicks=Array.from(leadersClicksByKey.values());patch.top.leaders=Array.from(leadersByKey.values());if(!patch.top.leaders.length&&patch.top.leadersViews.length)patch.top.leaders=patch.top.leadersViews.map(r=>({...r}));patch.top.profiles=Array.from(profilesByKey.values());if(!patch.top.leaders.length)delete patch.top.leaders;if(!patch.top.leadersViews.length)delete patch.top.leadersViews;if(!patch.top.leadersClicks.length)delete patch.top.leadersClicks;';
if (!s.includes('patch.top.leadersViews=Array.from(leadersViewsByKey')) {
  if (!s.includes(csvEndOld)) throw new Error('CSV import end block not found');
  s = s.replace(csvEndOld, csvEndNew);
}

// Pulse chart: controlled fraction inputs (flush on save via cfg state)
const fracInputOld =
  'defaultValue:Number(fr).toFixed(2),onFocus:ensureCustom,onChange:e=>setFracAt(i,e.target.value,false),onBlur:e=>{setFracAt(i,e.target.value,true);const f=parseFracInput(e.target.value);if(f!=null)e.target.value=Number(f).toFixed(2);}';
const fracInputNew =
  'value:Number(fr).toFixed(2),onFocus:ensureCustom,onChange:e=>setFracAt(i,e.target.value,false),onBlur:e=>{setFracAt(i,e.target.value,true);}';
if (s.includes(fracInputOld)) {
  s = s.replace(fracInputOld, fracInputNew);
}

fs.writeFileSync(path, s, 'utf8');
console.log('patched', path);
