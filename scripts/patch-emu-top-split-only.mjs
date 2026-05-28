/**
 * Split TOP / TOP META on a working HEAD+bundle (comma-fixed).
 * Only replaces emuPage==='top' … top_meta block (step 7 from page4 script).
 */
import fs from "node:fs";

const path = "new_frontend/app.bundle.js";
let s = fs.readFileSync(path, "utf8");

const start = s.indexOf("emuPage==='top'&&/*#__PURE__*/React.createElement(React.Fragment,null,");
if (start < 0) throw new Error("top page render start not found");
const end = s.indexOf(");}function EmuBroadcastScreen", start);
if (end < 0) throw new Error("top page render end not found");
const old = s.slice(start, end);

const topOnly = [
  "emuPage==='top'&&/*#__PURE__*/React.createElement(React.Fragment,null,",
  "/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)',letterSpacing:'0.18em',margin:'0 0 10px'}},\"TOP MOVERS · лидеры\"),",
  "(cfg.top.leadersViews||cfg.top.leaders||[]).slice(0,5).map((row,idx)=>/*#__PURE__*/React.createElement(\"div\",{key:(row.id||idx),style:{marginBottom:20,padding:14,borderRadius:14,border:'1px solid var(--line-2)'}},",
  "/*#__PURE__*/React.createElement(\"div\",{style:{display:'flex',alignItems:'center',gap:12,marginBottom:12}},",
  "/*#__PURE__*/React.createElement(AccountAvatar,{src:row.avatarUrl||_emuResolveLeaderAvatar(row),name:row.name||row.username,size:44,borderColor:\"rgba(106,169,255,0.35)\"}),",
  "/*#__PURE__*/React.createElement(\"div\",{style:{flex:1,minWidth:0}},",
  "/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)',marginBottom:6}},\"TOP V #\",idx+1,\" · @\",row.username),",
  "/*#__PURE__*/React.createElement(\"label\",{style:{display:'block',fontSize:11,color:'var(--ink-dim)'}},\"URL аватара (пусто — из API/кэша)\",/*#__PURE__*/React.createElement(\"input\",{type:\"url\",value:row.avatarUrl||'',placeholder:\"https://…\",onChange:e=>{const avatarUrl=e.target.value.trim();setCfg(c=>{const leaders=(c.top.leadersViews||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],avatarUrl};return{...c,top:{...c.top,leadersViews:leaders}};});},style:{display:'block',width:'100%',marginTop:4,padding:'8px',borderRadius:8,border:'1px solid var(--line)',background:'rgba(0,0,0,0.2)',color:'var(--ink)',fontSize:12}}))",
  ")),",
  "/*#__PURE__*/React.createElement(\"label\",{style:{fontSize:11,color:'var(--ink-dim)'}},\"Views total (старт)\",/*#__PURE__*/React.createElement(\"input\",{type:\"number\",step:\"1\",min:\"0\",value:Number(row.viewsStart||0),onChange:e=>{const viewsStart=Math.max(0,Math.round(Number(e.target.value)||0));setCfg(c=>{const leaders=(c.top.leadersViews||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],viewsStart};return{...c,top:{...c.top,leadersViews:leaders}};});},style:{display:\"block\",width:\"100%\",marginTop:4,padding:\"8px\",borderRadius:8,border:\"1px solid var(--line)\",background:\"rgba(0,0,0,0.2)\",color:\"var(--ink)\",fontSize:12}})),",
  "/*#__PURE__*/React.createElement(EmuChannelFields,{label:\"Δ просмотров (24h)\",channel:row.dViews,onChange:ch=>{setCfg(c=>{const leaders=(c.top.leadersViews||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],dViews:ch};return{...c,top:{...c.top,leadersViews:leaders}};});}})",
  ")),",
  "/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)',letterSpacing:'0.18em',margin:'18px 0 10px'}},\"TOP CLICKS · лидеры\"),",
  "(cfg.top.leadersClicks||cfg.top.leaders||[]).slice(0,5).map((row,idx)=>/*#__PURE__*/React.createElement(\"div\",{key:(row.id||idx),style:{marginBottom:20,padding:14,borderRadius:14,border:'1px solid var(--line-2)'}},",
  "/*#__PURE__*/React.createElement(\"div\",{style:{display:'flex',alignItems:'center',gap:12,marginBottom:12}},",
  "/*#__PURE__*/React.createElement(AccountAvatar,{src:row.avatarUrl||_emuResolveLeaderAvatar(row),name:row.name||row.username,size:44,borderColor:\"rgba(167,139,250,0.35)\"}),",
  "/*#__PURE__*/React.createElement(\"div\",{style:{flex:1,minWidth:0}},",
  "/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)',marginBottom:6}},\"TOP C #\",idx+1,\" · @\",row.username),",
  "/*#__PURE__*/React.createElement(\"label\",{style:{display:'block',fontSize:11,color:'var(--ink-dim)'}},\"URL аватара (пусто — из API/кэша)\",/*#__PURE__*/React.createElement(\"input\",{type:\"url\",value:row.avatarUrl||'',placeholder:\"https://…\",onChange:e=>{const avatarUrl=e.target.value.trim();setCfg(c=>{const leaders=(c.top.leadersClicks||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],avatarUrl};return{...c,top:{...c.top,leadersClicks:leaders}};});},style:{display:'block',width:'100%',marginTop:4,padding:'8px',borderRadius:8,border:'1px solid var(--line)',background:'rgba(0,0,0,0.2)',color:'var(--ink)',fontSize:12}}))",
  ")),",
  "/*#__PURE__*/React.createElement(\"label\",{style:{fontSize:11,color:'var(--ink-dim)'}},\"Clicks total (старт)\",/*#__PURE__*/React.createElement(\"input\",{type:\"number\",step:\"1\",min:\"0\",value:Number(row.clicksStart||0),onChange:e=>{const clicksStart=Math.max(0,Math.round(Number(e.target.value)||0));setCfg(c=>{const leaders=(c.top.leadersClicks||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],clicksStart};return{...c,top:{...c.top,leadersClicks:leaders}};});},style:{display:\"block\",width:\"100%\",marginTop:4,padding:\"8px\",borderRadius:8,border:\"1px solid var(--line)\",background:\"rgba(0,0,0,0.2)\",color:\"var(--ink)\",fontSize:12}})),",
  "/*#__PURE__*/React.createElement(EmuChannelFields,{label:\"Δ кликов (24h)\",channel:row.dClicks,onChange:ch=>{setCfg(c=>{const leaders=(c.top.leadersClicks||c.top.leaders||[]).slice();leaders[idx]={...leaders[idx],dClicks:ch};return{...c,top:{...c.top,leadersClicks:leaders}};});}})))),",
  "emuPage==='top_meta'&&/*#__PURE__*/React.createElement(React.Fragment,null,",
  "/*#__PURE__*/React.createElement(\"div\",{style:{display:'flex',flexWrap:'wrap',gap:10,alignItems:'center',margin:'8px 0 14px'}},/*#__PURE__*/React.createElement(\"button\",{type:\"button\",onClick:syncProfilesFromDashboard,style:{padding:'8px 14px',borderRadius:10,border:'1px solid var(--line)',background:'rgba(255,255,255,0.04)',color:'var(--ink)',cursor:'pointer',fontSize:13}},\"Синхронизировать с дашбордом\"),profilesAvailableToAdd.length>0?/*#__PURE__*/React.createElement(\"label\",{style:{display:'flex',alignItems:'center',gap:8,fontSize:13,color:'var(--ink-dim)'}},/*#__PURE__*/React.createElement(\"span\",null,\"+ Добавить профиль\"),/*#__PURE__*/React.createElement(\"select\",{defaultValue:\"\",onChange:e=>{const id=e.target.value;if(!id)return;addProfile(id);e.target.value='';},style:{padding:'8px 10px',borderRadius:8,border:'1px solid var(--line)',background:'rgba(0,0,0,0.25)',color:'var(--ink)',minWidth:200}},/*#__PURE__*/React.createElement(\"option\",{value:\"\"},\"— выберите —\"),profilesAvailableToAdd.map(p=>/*#__PURE__*/React.createElement(\"option\",{key:p.id,value:p.id},p.label,\" (\",byProfileCount.get(String(p.id))??p.accounts??0,\" акк.)\")))):/*#__PURE__*/React.createElement(\"span\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)'}},\"Все профили дашборда уже добавлены\")),",
  "(cfg.top.profiles||[]).length===0?/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:12,color:'var(--ink-mute)',marginBottom:16}},\"Нет профилей в эмуляции.\"):null,",
  "cfg.top.profiles.map((p,idx)=>/*#__PURE__*/React.createElement(EmuProfileFields,{key:`${p.id}-${idx}`,profile:p,onChange:next=>{setCfg(c=>{const profiles=c.top.profiles.slice();profiles[idx]=next;return{...c,top:{...c.top,profiles}};});},onDelete:()=>{void removeProfile(idx);}})),",
  "/*#__PURE__*/React.createElement(\"div\",{className:\"mono\",style:{fontSize:11,color:'var(--ink-mute)',margin:'16px 0 8px'}},\"Платформы · аккаунты и клики\"),",
  "NF_EMU_PLATFORM_IDS.map(id=>/*#__PURE__*/React.createElement(\"div\",{key:`top-plat-${id}`,style:{display:'grid',gridTemplateColumns:'1fr',gap:0}},/*#__PURE__*/React.createElement(EmuChannelFields,{label:`${id} · аккаунтов`,channel:cfg.top.platformAccounts[id],onChange:ch=>{setCfg(c=>({...c,top:{...c.top,platformAccounts:{...c.top.platformAccounts,[id]:ch}}}));}}),/*#__PURE__*/React.createElement(EmuChannelFields,{label:`${id} · кликов`,channel:cfg.top.platformClicks[id],onChange:ch=>{setCfg(c=>({...c,top:{...c.top,platformClicks:{...c.top.platformClicks,[id]:ch}}}));}}))))",
].join("");

if (!old.startsWith("emuPage==='top'")) throw new Error("unexpected old block");
s = s.slice(0, start) + topOnly + s.slice(end);
fs.writeFileSync(path, s, "utf8");
console.log("patched top split, old len", old.length, "new len", topOnly.length);
