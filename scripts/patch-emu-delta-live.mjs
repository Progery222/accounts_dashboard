#!/usr/bin/env node
import fs from 'fs';
import path from 'path';

const root = path.resolve(import.meta.dirname, '..');
const targets = [
  path.join(root, 'new_frontend', 'app.bundle.js'),
  path.join(root, 'new_frontend', 'app.bundle.from-server.js'),
].filter((p) => fs.existsSync(p));

const replacements = [
  [
    '// ── SCENE 2: Pulse / dynamics — sparklines per platform & profile ──\nfunction ScenePulse({accent,mood,pulse,emuMode=false}){const isMobile=useIsMobile(980);',
    '// ── SCENE 2: Pulse / dynamics — sparklines per platform & profile ──\nfunction ScenePulse({accent,mood,pulse,emuMode=false}){const[,setEmuPulseRev]=React.useState(0);React.useEffect(()=>{if(!NF_EMU_RUNTIME)return undefined;const iv=window.setInterval(()=>setEmuPulseRev(n=>n+1),400);return()=>window.clearInterval(iv);},[]);const isMobile=useIsMobile(980);',
  ],
  [
    'const candidates=(PLATFORMS||[]).map((p,i)=>{const emuPr=NF_EMU_RUNTIME?.pulse?.platform?.[p.id];',
    'const candidates=(PLATFORMS||[]).map((p,i)=>{void 0;const emuPr=NF_EMU_RUNTIME?.pulse?.platform?.[p.id];',
  ],
  [
    'function SceneAtom({accent,mood}){const emuLive=!!NF_EMU_RUNTIME;const[floatPops,setFloatPops]=React.useState({followers:[],views:[],likes:[],posts:[]});',
    'function _emuAtomCard(key){if(!NF_EMU_RUNTIME)return null;const rt=NF_EMU_RUNTIME.atom?.[key];if(!rt)return null;return{value:Math.round(rt.value||0),delta:Math.round(rt.dayDelta||0),sparkPts:rt.sparkPts,cfg:rt.cfg};}function _emuViewsCard(){if(!NF_EMU_RUNTIME)return null;return{value:Math.round(NF_EMU_RUNTIME.pulse?.viewsTotal?.value||0),delta:Math.round(NF_EMU_RUNTIME.pulse?.viewsDayStart?.value||0),sparkPts:NF_EMU_RUNTIME.atom?.views?.sparkPts,cfg:NF_EMU_RUNTIME.atom?.views?.cfg};}function _emuAtomMetric(key,totalKey){if(NF_EMU_RUNTIME){const live=key===\'views\'?_emuViewsCard():_emuAtomCard(key);if(live)return{value:live.value,delta:live.delta};}const t=TOTAL[totalKey]||{};return{value:Number(t.value||0),delta:Number(t.delta||0)};}function SceneAtom({accent,mood}){const emuLive=!!NF_EMU_RUNTIME;const[emuRev,setEmuRev]=React.useState(0);React.useEffect(()=>{if(!emuLive)return undefined;let sig=\'\';const readSig=()=>[\'followers\',\'views\',\'likes\',\'posts\'].map(k=>{const m=_emuAtomMetric(k,k);return`${m.value}:${m.delta}`;}).join(\'|\');sig=readSig();const iv=window.setInterval(()=>{const next=readSig();if(next!==sig){sig=next;setEmuRev(n=>n+1);}},400);return()=>window.clearInterval(iv);},[emuLive]);const[floatPops,setFloatPops]=React.useState({followers:[],views:[],likes:[],posts:[]});',
  ],
  [
    "const items=[{key:'followers',label:'ПОДПИСЧИКИ',value:TOTAL.followers.value,delta:TOTAL.followers.delta,color:'#4ade80',spark:sparkFor('followers',TOTAL.followers.delta,TOTAL.followers.yesterdayDelta),floatPops:floatPops.followers,infoTitle:'Подписчики',infoText:'Мини-график: «Старт»/«Потолок» — шкала, «Значение при запуске» — высота при старте, «Перестройка графика (сек)» — как часто добавлять точку (0 = каждый тик).'},{key:'views',label:'ПРОСМОТРЫ',value:TOTAL.views.value,delta:TOTAL.views.delta,color:'#ec4899',spark:sparkFor('views',TOTAL.views.delta,TOTAL.views.yesterdayDelta),floatPops:floatPops.views,infoTitle:'Просмотры',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'},{key:'likes',label:'ЛАЙКИ',value:TOTAL.likes.value,delta:TOTAL.likes.delta,color:'#f59e0b',spark:sparkFor('likes',TOTAL.likes.delta,TOTAL.likes.yesterdayDelta),floatPops:floatPops.likes,infoTitle:'Лайки',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'},{key:'posts',label:'ПУБЛИКАЦИИ',value:TOTAL.posts.value,delta:TOTAL.posts.delta,color:accent,spark:sparkFor('posts',TOTAL.posts.delta,TOTAL.posts.yesterdayDelta),floatPops:floatPops.posts,infoTitle:'Публикации',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'}];",
    "void emuRev;const _m=k=>_emuAtomMetric(k,k);const mf=_m('followers');const mv=_m('views');const ml=_m('likes');const mp=_m('posts');const items=[{key:'followers',label:'ПОДПИСЧИКИ',value:mf.value,delta:mf.delta,color:'#4ade80',spark:sparkFor('followers',mf.delta,TOTAL.followers.yesterdayDelta),floatPops:floatPops.followers,infoTitle:'Подписчики',infoText:'Мини-график: «Старт»/«Потолок» — шкала, «Значение при запуске» — высота при старте, «Перестройка графика (сек)» — как часто добавлять точку (0 = каждый тик).'},{key:'views',label:'ПРОСМОТРЫ',value:mv.value,delta:mv.delta,color:'#ec4899',spark:sparkFor('views',mv.delta,TOTAL.views.yesterdayDelta),floatPops:floatPops.views,infoTitle:'Просмотры',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'},{key:'likes',label:'ЛАЙКИ',value:ml.value,delta:ml.delta,color:'#f59e0b',spark:sparkFor('likes',ml.delta,TOTAL.likes.yesterdayDelta),floatPops:floatPops.likes,infoTitle:'Лайки',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'},{key:'posts',label:'ПУБЛИКАЦИИ',value:mp.value,delta:mp.delta,color:accent,spark:sparkFor('posts',mp.delta,TOTAL.posts.yesterdayDelta),floatPops:floatPops.posts,infoTitle:'Публикации',infoText:'Мини-график за 24h. «Старт» — низ, «Потолок» — верх, «Значение при запуске» — высота при старте.'}];",
  ],
];

// Fix ScenePulse: use emuPulseRev instead of void 0
const pulseFix = [
  'const candidates=(PLATFORMS||[]).map((p,i)=>{void 0;const emuPr=NF_EMU_RUNTIME?.pulse?.platform?.[p.id];',
  'const candidates=(PLATFORMS||[]).map((p,i)=>{void emuPulseRev;const emuPr=NF_EMU_RUNTIME?.pulse?.platform?.[p.id];',
];

for (const file of targets) {
  let s = fs.readFileSync(file, 'utf8');
  let changed = false;
  for (const [from, to] of replacements) {
    if (!s.includes(from)) {
      console.error(`[${path.basename(file)}] MISSING:\n${from.slice(0, 80)}...`);
      process.exitCode = 1;
      continue;
    }
    s = s.replace(from, to);
    changed = true;
  }
  for (const [from, to] of pulseFix) {
    if (s.includes(from)) {
      s = s.replace(from, to);
      changed = true;
    }
  }
  if (changed) {
    fs.writeFileSync(file, s);
    console.log(`Patched ${file}`);
  }
}
