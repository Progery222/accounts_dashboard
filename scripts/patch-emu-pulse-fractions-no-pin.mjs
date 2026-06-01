import fs from 'node:fs';

const path = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(path, 'utf8');

const enforceOld =
  'function _emuEnforceMonotonicFractions(raw,n=NF_EMU_PULSE_CHART_HOURS){const cnt=Math.max(2,Number(n)||NF_EMU_PULSE_CHART_HOURS);const src=Array.isArray(raw)?raw:[];const out=[];let prev=0;for(let i=0;i<cnt;i+=1){let f=i<src.length?Number(src[i]):i/(cnt-1);if(!Number.isFinite(f))f=prev;f=Math.max(0,Math.min(1,f));f=Math.max(prev,f);out.push(f);prev=f;}if(out.length){out[0]=0;out[out.length-1]=1;}return out;}';
const enforceNew =
  'function _emuEnforceMonotonicFractions(raw,n=NF_EMU_PULSE_CHART_HOURS){const cnt=Math.max(2,Number(n)||NF_EMU_PULSE_CHART_HOURS);const src=Array.isArray(raw)?raw:[];const out=[];let prev=0;for(let i=0;i<cnt;i+=1){let f=i<src.length?Number(src[i]):prev;if(!Number.isFinite(f))f=prev;f=Math.max(0,Math.min(1,f));f=Math.max(prev,f);out.push(f);prev=f;}return out;}function _emuPulseFractionAt(fr,idx){const arr=Array.isArray(fr)?fr:[];if(!arr.length)return 0;const i=Math.min(arr.length-1,Math.max(0,Number(idx)||0));const top=Math.max(...arr.map(x=>Number(x)||0),1e-9);return Math.min(1,Math.max(0,(Number(arr[i])||0)/top));}';
if (!s.includes(enforceNew)) {
  if (!s.includes(enforceOld)) throw new Error('_emuEnforceMonotonicFractions not found');
  s = s.replace(enforceOld, enforceNew);
}

const valuesOld =
  'function _emuPulseChartValuesFromFractions(dayDelta,fractions,hours=NF_EMU_PULSE_CHART_HOURS){const cap=Math.max(0,Math.round(Number(dayDelta)||0));const cnt=Math.max(2,Number(hours)||NF_EMU_PULSE_CHART_HOURS);const fr=_emuEnforceMonotonicFractions(fractions,cnt);const values=fr.map(f=>Math.round(cap*Math.max(0,Math.min(1,Number(f)||0))));for(let i=1;i<values.length;i+=1)values[i]=Math.max(values[i],values[i-1]);if(values.length&&cap>0)values[values.length-1]=Math.max(values[values.length-1],cap);return values;}';
const valuesNew =
  'function _emuPulseChartValuesFromFractions(dayDelta,fractions,hours=NF_EMU_PULSE_CHART_HOURS){const cap=Math.max(0,Math.round(Number(dayDelta)||0));const cnt=Math.max(2,Number(hours)||NF_EMU_PULSE_CHART_HOURS);const fr=_emuEnforceMonotonicFractions(fractions,cnt);const top=Math.max(...fr.map(x=>Number(x)||0),1e-9);const values=fr.map(f=>cap>0?Math.round(cap*Math.max(0,Math.min(1,Number(f)||0))/top):0);for(let i=1;i<values.length;i+=1)values[i]=Math.max(values[i],values[i-1]);return values;}';
if (!s.includes(valuesNew)) {
  if (!s.includes(valuesOld)) throw new Error('_emuPulseChartValuesFromFractions not found');
  s = s.replace(valuesOld, valuesNew);
}

const fracOld =
  'function _emuPulseFracAtTs(tsMs,dayDelta,cfg){const hours=NF_EMU_PULSE_CHART_HOURS;const calIdx=new Date(Number(tsMs)||Date.now()).getHours()%hours;const chart=cfg?.pulse?.viewsChart;const cap=Math.max(0,Number(dayDelta||0))||_emuPulseChartDayCap(cfg);let fr;if(chart?.mode===\'custom\'&&Array.isArray(chart.fractions)&&chart.fractions.length>=2){fr=_emuEnforceMonotonicFractions(chart.fractions,hours);}else{fr=_jaggedCumulativeFractions(hours,cap+17);}return fr[calIdx]??0;}';
const fracNew =
  'function _emuPulseFracAtTs(tsMs,dayDelta,cfg){const hours=NF_EMU_PULSE_CHART_HOURS;const calIdx=new Date(Number(tsMs)||Date.now()).getHours()%hours;const chart=cfg?.pulse?.viewsChart;const cap=Math.max(0,Number(dayDelta||0))||_emuPulseChartDayCap(cfg);let fr;if(chart?.mode===\'custom\'&&Array.isArray(chart.fractions)&&chart.fractions.length>=2){fr=_emuEnforceMonotonicFractions(chart.fractions,hours);}else{fr=_jaggedCumulativeFractions(hours,cap+17);}return _emuPulseFractionAt(fr,calIdx);}';
if (!s.includes(fracNew)) {
  if (!s.includes(fracOld)) throw new Error('_emuPulseFracAtTs not found');
  s = s.replace(fracOld, fracNew);
}

const editorCapOld = 'const cap=Math.max(0,Math.round(Number(dayCap)||0))||1;';
const editorCapNew = 'const cap=Math.max(0,Math.round(Number(dayCap)||0));';
if (s.includes(editorCapOld)) {
  s = s.replace(editorCapOld, editorCapNew);
}

const dayCapPropOld =
  'dayCap:cfg.pulse?.viewsDayStart?.max??cfg.pulse?.viewsDayStart?.start??2500,onChange:vc=>setCfg';
const dayCapPropNew =
  'dayCap:(()=>{const ch=cfg.pulse?.viewsDayStart;const c=_emuCap(ch);if(c!=null)return c;return Math.max(0,Number(ch?.start)||0);})(),onChange:vc=>setCfg';
if (!s.includes(dayCapPropNew)) {
  if (!s.includes(dayCapPropOld)) throw new Error('EmuPulseChartEditor dayCap prop not found');
  s = s.replace(dayCapPropOld, dayCapPropNew);
}

fs.writeFileSync(path, s, 'utf8');
console.log('patched', path);
