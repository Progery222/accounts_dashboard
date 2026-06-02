/**
 * Секция «Способ сбора данных» на /settings + badge Apify в списке аккаунтов.
 */
import fs from "fs";

const p = "c:/Users/Mobile Farm/Documents/dashboard/new_frontend/app.bundle.js";
let b = fs.readFileSync(p, "utf8");

const marker = '// Settings (auth) screen — atomic-themed redesign of "Настройки авторизации".';
if (!b.includes(marker)) throw new Error("settings marker not found");
if (b.includes("function ScrapeBackendSettingsPanel")) {
  console.log("already patched");
  process.exit(0);
}

const insertAfterMarker = `${marker}
function ScrapeBackendSettingsPanel(){
  const [cfg,setCfg]=React.useState(null);
  const [draft,setDraft]=React.useState(null);
  const [loading,setLoading]=React.useState(true);
  const [saving,setSaving]=React.useState(false);
  const [err,setErr]=React.useState('');
  const load=React.useCallback(async()=>{setLoading(true);setErr('');try{const d=await _fetchJson('/api/accounts/scrape-backend/');setCfg(d);setDraft({facebook_backend:d.facebook_backend||'playwright',tiktok_backend:d.tiktok_backend||'playwright',instagram_backend:d.instagram_backend||'playwright',youtube_backend:d.youtube_backend||'playwright',reddit_backend:d.reddit_backend||'playwright',rumble_backend:d.rumble_backend||'playwright'});}catch(e){setErr(e?.message||String(e));setDraft(null);}finally{setLoading(false);}},[]);
  React.useEffect(()=>{void load();},[load]);
  const apifyOk=!!(cfg&&cfg.apify_enabled);
  const rows=[['Facebook','facebook_backend'],['TikTok','tiktok_backend'],['Instagram','instagram_backend'],['YouTube','youtube_backend'],['Reddit','reddit_backend'],['Rumble','rumble_backend']];
  const save=async()=>{if(!draft)return;setSaving(true);setErr('');try{const d=await _fetchJson('/api/accounts/scrape-backend/',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});setCfg(d);setDraft({facebook_backend:d.facebook_backend||'playwright',tiktok_backend:d.tiktok_backend||'playwright',instagram_backend:d.instagram_backend||'playwright',youtube_backend:d.youtube_backend||'playwright',reddit_backend:d.reddit_backend||'playwright',rumble_backend:d.rumble_backend||'playwright'});}catch(e){setErr(e?.message||String(e));}finally{setSaving(false);}};
  return /*#__PURE__*/React.createElement('section',{style:{marginTop:28,padding:20,borderRadius:14,border:'1px solid rgba(255,255,255,0.08)',background:'rgba(0,0,0,0.25)'}},/*#__PURE__*/React.createElement('h2',{style:{margin:'0 0 6px',fontSize:18,fontWeight:700}},'Способ сбора данных'),/*#__PURE__*/React.createElement('p',{style:{margin:'0 0 16px',fontSize:13,color:'var(--ink-dim)',lineHeight:1.45}},'Настройки хранятся на сервере. Изменения действуют только на новые запуски обновления. Аудитория всегда через Playwright.'),loading?/*#__PURE__*/React.createElement('p',{style:{margin:'0 0 12px',fontSize:13,color:'var(--ink-dim)'}},'Загрузка…'):null,!loading&&!draft&&err?/*#__PURE__*/React.createElement('p',{style:{margin:'0 0 12px',fontSize:12,color:'#f87171'}},err,' ',/*#__PURE__*/React.createElement('button',{type:'button',onClick:()=>void load(),style:{marginLeft:8,padding:'4px 10px',borderRadius:6,border:'1px solid rgba(255,255,255,0.2)',background:'transparent',color:'inherit',cursor:'pointer'}},'Повторить')):null,!loading&&draft?/*#__PURE__*/React.createElement(React.Fragment,null,!apifyOk?/*#__PURE__*/React.createElement('p',{style:{margin:'0 0 12px',fontSize:12,color:'#f59e0b'}},'Apify недоступен: задайте APIFY_ENABLED=1 и APIFY_TOKEN.'):null,cfg&&cfg.apify_active_jobs>0?/*#__PURE__*/React.createElement('p',{style:{margin:'0 0 12px',fontSize:13,color:'var(--ink-dim)'}},'Активных задач Apify: ',cfg.apify_active_jobs):null,...rows.map(([label,key])=>/*#__PURE__*/React.createElement('label',{key:key,style:{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,marginBottom:10,fontSize:14}},/*#__PURE__*/React.createElement('span',null,label),/*#__PURE__*/React.createElement('select',{value:draft[key],disabled:saving||!apifyOk&&draft[key]==='apify',onChange:e=>setDraft(d=>({...d,[key]:e.target.value})),style:{minWidth:140,padding:'6px 10px',borderRadius:8,background:'rgba(255,255,255,0.06)',color:'inherit',border:'1px solid rgba(255,255,255,0.12)'}},/*#__PURE__*/React.createElement('option',{value:'playwright',style:{background:'#111827',color:'#e5e7eb'}},'Playwright'),/*#__PURE__*/React.createElement('option',{value:'apify',disabled:!apifyOk,style:{background:'#111827',color:'#e5e7eb'}},'Apify'+(apifyOk?'':' (выкл.)'))))),err&&draft?/*#__PURE__*/React.createElement('p',{style:{color:'#f87171',fontSize:12,margin:'8px 0'}},err):null,/*#__PURE__*/React.createElement('button',{type:'button',disabled:saving||!draft,onClick:()=>void save(),style:{marginTop:8,padding:'8px 16px',borderRadius:8,border:'none',background:'#3b82f6',color:'#fff',fontWeight:600,cursor:saving?'wait':'pointer'}},saving?'Сохранение…':'Сохранить')):null);
}
`;

b = b.replace(marker, insertAfterMarker);

const settingsNeedle =
  "route==='settings'&&/*#__PURE__*/React.createElement(SettingsScreen,{key:`set-${dataKey}`,tweaks:tweaks,onBack:()=>setRoute('accounts'),onDataChanged:reloadData,onOpenGlobalModal:setGlobalModal})";
const settingsReplace =
  "route==='settings'&&/*#__PURE__*/React.createElement(React.Fragment,{key:`set-wrap-${dataKey}`},/*#__PURE__*/React.createElement(SettingsScreen,{key:`set-${dataKey}`,tweaks:tweaks,onBack:()=>setRoute('accounts'),onDataChanged:reloadData,onOpenGlobalModal:setGlobalModal}),/*#__PURE__*/React.createElement(ScrapeBackendSettingsPanel,null))";
if (!b.includes(settingsNeedle)) throw new Error("SettingsScreen route block not found");
b = b.replace(settingsNeedle, settingsReplace);

const badgeNeedle = "account.updated_at";
if (b.includes("refresh_pipeline_label")) {
  console.log("account badge already present");
} else {
  const rowNeedle = "account.username";
  const injectBadge =
    "account.refresh_pipeline_label&&/*#__PURE__*/React.createElement('span',{style:{marginLeft:8,fontSize:11,padding:'2px 8px',borderRadius:999,background:'rgba(59,130,246,0.2)',color:'#93c5fd',whiteSpace:'nowrap'}},account.refresh_pipeline_label),";
  if (!b.includes(rowNeedle)) throw new Error("account.username in list not found");
  b = b.replace(rowNeedle, injectBadge + rowNeedle);
}

fs.writeFileSync(p, b);
console.log("patch-scrape-backend-settings: ok");
