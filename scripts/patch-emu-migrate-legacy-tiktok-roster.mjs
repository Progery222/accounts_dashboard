/**
 * Replace legacy all-TikTok TOP roster in localStorage with canonical 2 FB / 2 TT / 1 IG.
 */
import fs from 'node:fs';
import path from 'node:path';

const bundlePath = path.join(process.cwd(), 'new_frontend', 'app.bundle.js');
let s = fs.readFileSync(bundlePath, 'utf8');

const oldFn =
  'function _emuMigrateTopLeaders(cfg){if(!cfg?.top)return cfg;const fixRow=(row,idx)=>{if(!row||typeof row!==\'object\')return row;const u=String(row.username||\'\').toLowerCase();let next={...row};if(u===\'debtceiling\')Object.assign(next,{id:row.id||5,name:\'Yllazen Music\',username:\'yllazenmusic\',platform:\'instagram\',profile:\'2\'});else if(u===\'freemarketsignal\')Object.assign(next,{id:row.id||4,name:\'Yllazen\',username:\'yllazenofficial\',platform:\'tiktok\',profile:\'2\'});if(u===\'philthetruth\'&&String(row.platform||\'\')===\'facebook\')Object.assign(next,{name:\'Phil Signal\',username:\'61589378772402\',profile:\'1\'});if(u===\'sovereigndesk\'&&String(row.platform||\'\')===\'facebook\')Object.assign(next,{name:\'Bob Seemens\',username:\'61588868450712\',profile:\'1\'});next.profile=_emuResolveLeaderProfile(next);return next;};const mapList=arr=>Array.isArray(arr)?arr.map((r,i)=>fixRow(r,i)):arr;return{...cfg,top:{...cfg.top,leadersViews:mapList(cfg.top.leadersViews),leadersClicks:mapList(cfg.top.leadersClicks),leaders:mapList(cfg.top.leaders)}};}';

const newFn =
  "function _emuMigrateTopLeaders(cfg){if(!cfg?.top)return cfg;const LEGACY5=['philthetruth','market.decoded8','sovereigndesk','yllazenofficial','yllazenmusic'];const isLegacyTiktokRoster=list=>{if(!Array.isArray(list)||list.length<5)return false;const top5=list.slice(0,5);const usernames=new Set(top5.map(r=>String(r.username||'').toLowerCase()));return LEGACY5.every(u=>usernames.has(u))&&top5.every(r=>String(r.platform||'').toLowerCase()==='tiktok');};const canon=_emuDefaultConfig().top;const fixRow=(row,idx)=>{if(!row||typeof row!=='object')return row;const u=String(row.username||'').toLowerCase();let next={...row};if(u==='debtceiling')Object.assign(next,{id:row.id||5,name:'Yllazen Music',username:'yllazenmusic',platform:'instagram',profile:'2'});else if(u==='freemarketsignal')Object.assign(next,{id:row.id||4,name:'Yllazen',username:'yllazenofficial',platform:'tiktok',profile:'2'});else if(u==='philthetruth')Object.assign(next,{name:'Phil Signal',username:'61589378772402',platform:'facebook',profile:'1'});else if(u==='sovereigndesk')Object.assign(next,{name:'Bob Seemens',username:'61588868450712',platform:'facebook',profile:'1'});next.profile=_emuResolveLeaderProfile(next);return next;};const mapList=(arr,key)=>{if(!Array.isArray(arr))return arr;if(isLegacyTiktokRoster(arr)){const base=(canon[key]||canon.leadersViews||[]).map(r=>({...r}));return base.map((row,i)=>{const old=arr[i];if(!old||typeof old!=='object')return fixRow(row,i);return fixRow({...row,dViews:old.dViews?{...row.dViews,...old.dViews}:row.dViews,dClicks:old.dClicks?{...row.dClicks,...old.dClicks}:row.dClicks,viewsStart:old.viewsStart??row.viewsStart,clicksStart:old.clicksStart??row.clicksStart},i);});}return arr.map((r,i)=>fixRow(r,i));};return{...cfg,top:{...cfg.top,leadersViews:mapList(cfg.top.leadersViews,'leadersViews'),leadersClicks:mapList(cfg.top.leadersClicks,'leadersClicks'),leaders:mapList(cfg.top.leaders,'leaders')}};}";

if (!s.includes(oldFn)) {
  if (s.includes('isLegacyTiktokRoster')) {
    console.log('patch-emu-migrate-legacy-tiktok-roster: already applied');
    process.exit(0);
  }
  console.error('patch-emu-migrate-legacy-tiktok-roster: _emuMigrateTopLeaders block not found');
  process.exit(1);
}

s = s.replace(oldFn, newFn);

const oldLoad =
  "function _emuLoadConfig(){try{const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw)return _emuDefaultConfig();const parsed=JSON.parse(raw);return _emuMigrateTopLeaders(_emuMergeConfig(_emuDefaultConfig(),parsed));}catch(_){return _emuDefaultConfig();}}";

const newLoad =
  "function _emuLoadConfig(){try{const raw=window.localStorage.getItem(NF_EMU_STORAGE_KEY);if(!raw)return _emuDefaultConfig();const parsed=JSON.parse(raw);const merged=_emuMergeConfig(_emuDefaultConfig(),parsed);const migrated=_emuMigrateTopLeaders(merged);const before=JSON.stringify(merged.top?.leadersViews||[]);const after=JSON.stringify(migrated.top?.leadersViews||[]);if(before!==after){try{window.localStorage.setItem(NF_EMU_STORAGE_KEY,JSON.stringify(migrated));}catch(_){}}return migrated;}catch(_){return _emuDefaultConfig();}}";

if (s.includes(oldLoad)) {
  s = s.replace(oldLoad, newLoad);
} else if (!s.includes('const migrated=_emuMigrateTopLeaders(merged)')) {
  console.error('patch-emu-migrate-legacy-tiktok-roster: _emuLoadConfig block not found');
  process.exit(1);
}

fs.writeFileSync(bundlePath, s);
console.log('patch-emu-migrate-legacy-tiktok-roster: OK');
