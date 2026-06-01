/**
 * Pulse chart: no flat top plateau; fractions not pinned to 0/1; TV emu 30s hold.
 * Run on committed app.bundle.js (node --check must pass after).
 */
import fs from 'node:fs';

const path = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(path, 'utf8');

const helperFn =
  'function _emuScaleEmuPulseDrawPoints(points,liveNow,fixedCap){const live=Math.max(0,Math.round(Number(liveNow)||0));const pts=(Array.isArray(points)?points:[]).map(p=>({...p,value:Math.max(0,Number(p.value)||0)}));if(!pts.length)return pts;if(live<=0)return pts.map(p=>({...p,value:0}));const peak=Math.max(...pts.map(p=>p.value),1);const target=fixedCap>0?Math.min(live,fixedCap):live;if(peak<=target){return pts.map((p,i,arr)=>({...p,value:i===arr.length-1?target:Math.min(p.value,target)}));}const k=target/peak;return pts.map((p,i,arr)=>({...p,value:i===arr.length-1?target:Math.round(p.value*k)}));}';

if (!s.includes('_emuScaleEmuPulseDrawPoints')) {
  const anchor = 'function ScenePulse({accent,mood,pulse,emuMode=false})';
  if (!s.includes(anchor)) throw new Error('ScenePulse not found');
  s = s.replace(anchor, helperFn + anchor);
}

const bigOld =
  "if(emuMode){const cap=Math.max(dayDeltaForChart,1);const _chartMode=NF_EMU_RUNTIME?.cfg?.pulse?.viewsChart?.mode==='custom'?'custom':'auto';const _chartFr=_chartMode==='custom'?_emuPulseChartFractionsFromCfg(NF_EMU_RUNTIME?.cfg):null;let drawnPoints=_buildEmuPulseChartPoints(cap,windowEnd,24,_chartFr);const last=drawnPoints[drawnPoints.length-1];if(last&&last.ts<windowEnd&&last.value<cap){drawnPoints.push({ts:windowEnd,value:cap});}for(let i=1;i<drawnPoints.length;i+=1){if(drawnPoints[i].value<drawnPoints[i-1].value){drawnPoints[i].value=drawnPoints[i-1].value;}}const maxV=Math.max(...drawnPoints.map(p=>p.value),1);const scaleMin=0;const scaleMax=maxV+Math.max(1,Math.ceil(maxV*0.006));const plotTop=10;const plotBottom=14;const plotH=Math.max(40,h-plotTop-plotBottom);points=drawnPoints.map(p=>{const x=Math.max(0,Math.min(w,(p.ts-windowStart)/(windowEnd-windowStart||1)*w));const y=h-plotBottom-(p.value-scaleMin)/(scaleMax-scaleMin||1)*plotH;return[x,y,p.ts,p.value];});}else{";

const bigNew =
  "if(emuMode){const cap=Math.max(dayDeltaForChart,1);const _chartMode=NF_EMU_RUNTIME?.cfg?.pulse?.viewsChart?.mode==='custom'?'custom':'auto';const _chartFr=_chartMode==='custom'?_emuPulseChartFractionsFromCfg(NF_EMU_RUNTIME?.cfg):null;let drawnPoints=_buildEmuPulseChartPoints(cap,windowEnd,24,_chartFr);const _rt=NF_EMU_RUNTIME;const _liveNow=Math.max(0,Math.round(_rt?.pulse?.viewsDayStart?.value||0));const _chMax=_emuCap(_rt?.cfg?.pulse?.viewsDayStart);const _fixedCap=_chMax!=null?Math.round(_chMax):0;drawnPoints=_emuScaleEmuPulseDrawPoints(drawnPoints,_liveNow,_fixedCap);drawnPoints=drawnPoints.filter(p=>p.ts<=windowEnd+500);const _last=drawnPoints[drawnPoints.length-1];const _tailVal=_fixedCap>0?Math.min(_liveNow,_fixedCap):_liveNow;if(!_last){drawnPoints.push({ts:windowEnd,value:_tailVal});}else if(_last.ts<windowEnd-500){drawnPoints.push({ts:windowEnd,value:_tailVal});}else{drawnPoints[drawnPoints.length-1]={ts:windowEnd,value:_tailVal};}for(let i=1;i<drawnPoints.length;i+=1){if(drawnPoints[i].value<drawnPoints[i-1].value){drawnPoints[i].value=drawnPoints[i-1].value;}}const maxV=Math.max(...drawnPoints.map(p=>p.value),1);const scaleMin=0;const scaleMax=maxV+Math.max(1,Math.ceil(maxV*0.006));const plotTop=10;const plotBottom=14;const plotH=Math.max(40,h-plotTop-plotBottom);points=drawnPoints.map(p=>{const x=Math.max(0,Math.min(w,(p.ts-windowStart)/(windowEnd-windowStart||1)*w));const y=h-plotBottom-(p.value-scaleMin)/(scaleMax-scaleMin||1)*plotH;return[x,y,p.ts,p.value];});}else{";

if (!s.includes('_emuScaleEmuPulseDrawPoints(drawnPoints,_liveNow,_fixedCap)')) {
  if (!s.includes(bigOld)) throw new Error('BigChart emu block not found');
  s = s.replace(bigOld, bigNew);
}

const enforceOld =
  'function _emuEnforceMonotonicFractions(raw,n=NF_EMU_PULSE_CHART_HOURS){const cnt=Math.max(2,Number(n)||NF_EMU_PULSE_CHART_HOURS);const src=Array.isArray(raw)?raw:[];const out=[];let prev=0;for(let i=0;i<cnt;i+=1){let f=i<src.length?Number(src[i]):i/(cnt-1);if(!Number.isFinite(f))f=prev;f=Math.max(0,Math.min(1,f));f=Math.max(prev,f);out.push(f);prev=f;}if(out.length){out[0]=0;out[out.length-1]=1;}return out;}';
const enforceNew =
  'function _emuEnforceMonotonicFractions(raw,n=NF_EMU_PULSE_CHART_HOURS){const cnt=Math.max(2,Number(n)||NF_EMU_PULSE_CHART_HOURS);const src=Array.isArray(raw)?raw:[];const out=[];let prev=0;for(let i=0;i<cnt;i+=1){let f=i<src.length?Number(src[i]):prev;if(!Number.isFinite(f))f=prev;f=Math.max(0,Math.min(1,f));f=Math.max(prev,f);out.push(f);prev=f;}return out;}';

if (!s.includes('out[out.length-1]=1;}return out;}function _buildTrendFromSeries')) {
  if (!s.includes(enforceOld)) throw new Error('_emuEnforceMonotonicFractions not found');
  s = s.replace(enforceOld, enforceNew);
}

const valuesTailOld =
  'for(let i=1;i<values.length;i+=1)values[i]=Math.max(values[i],values[i-1]);if(values.length)values[values.length-1]=Math.max(values[values.length-1],cap);return values;}/** 24 почасовые';
const valuesTailNew =
  'for(let i=1;i<values.length;i+=1)values[i]=Math.max(values[i],values[i-1]);return values;}/** 24 почасовые';

if (s.includes(valuesTailOld)) {
  s = s.replace(valuesTailOld, valuesTailNew);
}

const tvHoldOld = 'const TV_SCENE_FADE_MS=1250;const TV_SCENE_HOLD_MS=6000;';
const tvHoldNew =
  'const TV_SCENE_FADE_MS=1250;const TV_SCENE_HOLD_MS=6000;const TV_EMU_SCENE_HOLD_MS=30000;';

if (!s.includes('TV_EMU_SCENE_HOLD_MS')) {
  if (!s.includes(tvHoldOld)) throw new Error('TV_SCENE_HOLD_MS not found');
  s = s.replace(tvHoldOld, tvHoldNew);
}

const tvEffectHeadOld =
  'useEffectTV(()=>{if(sceneAutoPaused)return undefined;let cancelled=false;let timerId=null;const scheduleNext=()=>{timerId=window.setTimeout(()=>{if(cancelled)return;setScene(s=>(s+1)%SCENES.length);scheduleNext();},TV_SCENE_HOLD_MS+TV_SCENE_FADE_MS);};timerId=window.setTimeout(scheduleNext,TV_SCENE_HOLD_MS);return()=>{cancelled=true;if(timerId!=null)window.clearTimeout(timerId);};},[sceneAutoPaused]);';
const tvEffectHeadNew =
  'useEffectTV(()=>{if(sceneAutoPaused)return undefined;const holdMs=emuMode?TV_EMU_SCENE_HOLD_MS:TV_SCENE_HOLD_MS;let cancelled=false;let timerId=null;const scheduleNext=()=>{timerId=window.setTimeout(()=>{if(cancelled)return;setScene(s=>(s+1)%SCENES.length);scheduleNext();},holdMs+TV_SCENE_FADE_MS);};timerId=window.setTimeout(scheduleNext,holdMs);return()=>{cancelled=true;if(timerId!=null)window.clearTimeout(timerId);};},[sceneAutoPaused,emuMode]);';

if (!s.includes('const holdMs=emuMode?TV_EMU_SCENE_HOLD_MS')) {
  if (!s.includes(tvEffectHeadOld)) throw new Error('TV scene useEffect not found');
  s = s.replace(tvEffectHeadOld, tvEffectHeadNew);
}

const editorCapOld =
  'dayCap:cfg.pulse?.viewsDayStart?.max??cfg.pulse?.viewsDayStart?.start??2500,onChange:vc=>setCfg';
const editorCapNew =
  'dayCap:(()=>{const ch=cfg.pulse?.viewsDayStart;const c=_emuCap(ch);if(c!=null)return c;return Math.max(0,Number(ch?.start)||0);})(),onChange:vc=>setCfg';

if (s.includes(editorCapOld)) {
  s = s.replace(editorCapOld, editorCapNew);
}

const editorCap2Old = 'const cap=Math.max(0,Math.round(Number(dayCap)||0))||1;';
const editorCap2New = 'const cap=Math.max(0,Math.round(Number(dayCap)||0));';
if (s.includes(editorCap2Old)) {
  s = s.replace(editorCap2Old, editorCap2New);
}

fs.writeFileSync(path, s, 'utf8');
console.log('patched', path);
