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
    "_EMU_CFG_CHANNEL_FIELDS=['start','stepMin','stepMax','intervalMinSec','intervalMaxSec','max','launchValue','sparkRebuildSec','seedDeltaMin','seedDeltaMax'];function _csvEscapeCell",
    "_EMU_CFG_CHANNEL_FIELDS=['start','stepMin','stepMax','intervalMinSec','intervalMaxSec','max','launchValue','sparkRebuildSec','seedDeltaMin','seedDeltaMax'];const _EMU_CFG_CSV_SPARK_FIELDS=new Set(['launchValue','sparkRebuildSec']);function _csvEscapeCell",
  ],
  [
    'function _emuCsvPushChannel(rows,section,path,ch){if(!ch||typeof ch!==\'object\')return;for(const f of _EMU_CFG_CHANNEL_FIELDS){if(ch[f]==null||ch[f]===\'\')continue;rows.push([section,path,f,ch[f]]);}}function _emuConfigToCsv(cfg)',
    'function _emuCsvPushChannel(rows,section,path,ch){if(!ch||typeof ch!==\'object\')return;const norm=_emuNormalizeChannel(ch);for(const f of _EMU_CFG_CHANNEL_FIELDS){const val=_EMU_CFG_CSV_SPARK_FIELDS.has(f)?norm[f]:ch[f];if(val==null||val===\'\')continue;rows.push([section,path,f,val]);}}function _emuPrepareConfigForCsv(cfg){return _emuHydrateConfigLeaders(_emuMergeConfig(_emuDefaultConfig(),cfg||{}));}function _emuConfigToCsv(cfg)',
  ],
  [
    'const exportCsv=()=>{const next=_emuHydrateConfigLeaders(cfg);_emuDownloadConfigCsv(next);',
    'const exportCsv=()=>{const next=_emuPrepareConfigForCsv(cfg);_emuDownloadConfigCsv(next);',
  ],
];

for (const file of targets) {
  let s = fs.readFileSync(file, 'utf8');
  let changed = false;
  for (const [from, to] of replacements) {
    if (!s.includes(from)) {
      console.error(`[${path.basename(file)}] MISSING:\n${from.slice(0, 100)}...`);
      process.exitCode = 1;
      continue;
    }
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
