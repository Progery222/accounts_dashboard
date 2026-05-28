#!/usr/bin/env node
/**
 * Patch app.bundle.js: configurable Platform Pulse (emu spark + settings).
 */
import fs from 'fs';
import path from 'path';

const root = path.resolve(import.meta.dirname, '..');
const targets = [
  path.join(root, 'new_frontend', 'app.bundle.js'),
  path.join(root, 'new_frontend', 'app.bundle.from-server.js'),
].filter((p) => fs.existsSync(p));

const replacements = [
  [
    'pulse.platform[id]={cfg:{...ch},..._emuInitRuntimeState(ch)};',
    'pulse.platform[id]={cfg:{...ch},..._emuInitRuntimeState(ch,true,`pulse-${id}`)};',
  ],
  [
    'function ResponsiveSpark({data,color,scaleMin=null,scaleMax=null,emuAtom=false,emuSparkCfg=null,plotH=null}){const w=600;const h=emuAtom?Number(plotH)>0?Number(plotH):320:60;const emuView=emuAtom&&emuSparkCfg?_emuAtomSparkPlot(data,emuSparkCfg):null;const plotData=emuView?emuView.plot:data;const plotOpts=emuAtom?{emuSpark:true,scaleMin:0,scaleMax:1,maxPadTop:NF_EMU_ATOM_SPARK_MAX_Y}:scaleMin!=null||scaleMax!=null?{scaleMin:scaleMin??0,scaleMax:scaleMax??10}:{};',
    'function ResponsiveSpark({data,color,scaleMin=null,scaleMax=null,emuAtom=false,emuSparkCfg=null,plotH=null}){const w=600;const h=emuAtom?Number(plotH)>0?Number(plotH):320:60;const emuView=emuAtom&&emuSparkCfg?_emuAtomSparkPlot(data,emuSparkCfg):null;const plotData=emuView?emuView.plot:data;const emuPadTop=h<80?Math.max(4,Math.round(h*0.42)):NF_EMU_ATOM_SPARK_MAX_Y;const plotOpts=emuAtom?{emuSpark:true,scaleMin:0,scaleMax:1,maxPadTop:emuPadTop}:scaleMin!=null||scaleMax!=null?{scaleMin:scaleMin??0,scaleMax:scaleMax??10}:{};',
  ],
  [
    "const showPlatformInfo=(e,label)=>openInfoPopover(e,`Platform Pulse · ${label}`,`Линия ${label}: почасовой прирост за 24 ч (спады и подъёмы). Число «+N» — итог за сутки. В эмуляции: «Настройки» → «СТРАНИЦА 2 · PULSE» → «Платформа · ${label}».`);",
    "const showPlatformInfo=(e,label)=>openInfoPopover(e,`Platform Pulse · ${label}`,`Линия ${label}: прирост за сутки. В эмуляции: «Настройки» → «СТРАНИЦА 2 · PULSE» → «Платформа · ${label}» — старт (низ графика), потолок (верх), значение при запуске, перестройка графика (сек). Число «+N» — прирост за сутки.`);",
  ],
  [
    'label:`Платформа · ${id} (дельта просмотров)`,channel:cfg.pulse.platform[id],onChange:ch=>setPulsePlat(id,ch)})',
    'label:`Платформа · ${id} (дельта просмотров)`,channel:cfg.pulse.platform[id],onChange:ch=>setPulsePlat(id,ch),showLaunchValue:true})',
  ],
  [
    'const candidates=(PLATFORMS||[]).map((p,i)=>{const pulse=_platformPulseFromSeries(series,p.id);',
    'const candidates=(PLATFORMS||[]).map((p,i)=>{const emuPr=NF_EMU_RUNTIME?.pulse?.platform?.[p.id];if(emuPr?.sparkPts?.length>=2){const value=Math.round(emuPr.dayDelta??emuPr.value??0);return{id:p.id,label:p.label,color:p.color,idx:i,hasReal:true,value,data:emuPr.sparkPts,emuSparkCfg:emuPr.cfg};}const pulse=_platformPulseFromSeries(series,p.id);',
  ],
  [
    '/*#__PURE__*/React.createElement(Sparkline,{data:data,color:p.color,width:1600,height:36,dot:false,fill:true,stretch:true})',
    '/*#__PURE__*/React.createElement(p.emuSparkCfg?ResponsiveSpark:Sparkline,p.emuSparkCfg?{data:data,color:p.color,emuAtom:true,emuSparkCfg:p.emuSparkCfg,plotH:36}:{data:data,color:p.color,width:1600,height:36,dot:false,fill:true,stretch:true})',
  ],
];

for (const file of targets) {
  let s = fs.readFileSync(file, 'utf8');
  const before = s;
  for (const [from, to] of replacements) {
    if (!s.includes(from)) {
      console.error(`[${path.basename(file)}] MISSING:\n${from.slice(0, 120)}...`);
      process.exitCode = 1;
      continue;
    }
    s = s.replace(from, to);
  }
  if (s !== before) {
    fs.writeFileSync(file, s);
    console.log(`Patched ${file}`);
  } else {
    console.log(`No changes ${file}`);
  }
}
