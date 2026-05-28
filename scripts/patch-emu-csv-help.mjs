#!/usr/bin/env node
import fs from 'fs';
import path from 'path';

const root = path.resolve(import.meta.dirname, '..');
const from =
  '" \\u2014 \\u0443\\u0434\\u043E\\u0431\\u043D\\u043E \\u043F\\u0440\\u0430\\u0432\\u0438\\u0442\\u044C \\u0432 Excel \\u0438 \\u043F\\u0435\\u0440\\u0435\\u043D\\u043E\\u0441\\u0438\\u0442\\u044C \\u043F\\u0440\\u0435\\u0441\\u0435\\u0442\\u044B \\u043C\\u0435\\u0436\\u0434\\u0443 \\u043C\\u0430\\u0448\\u0438\\u043D\\u0430\\u043C\\u0438.")';
const to =
  '" \\u2014 \\u043A\\u0430\\u043D\\u0430\\u043B: start, stepMin, stepMax, intervalMinSec, intervalMaxSec, max, launchValue, sparkRebuildSec. Pulse: path platform.youtube \\u0438 \\u0442.\\u043F. \\u0423\\u0434\\u043E\\u0431\\u043D\\u043E \\u043F\\u0440\\u0430\\u0432\\u0438\\u0442\\u044C \\u0432 Excel \\u0438 \\u043F\\u0435\\u0440\\u0435\\u043D\\u043E\\u0441\\u0438\\u0442\\u044C \\u043F\\u0440\\u0435\\u0441\\u0435\\u0442\\u044B.")';

for (const name of ['app.bundle.js', 'app.bundle.from-server.js']) {
  const file = path.join(root, 'new_frontend', name);
  if (!fs.existsSync(file)) continue;
  let s = fs.readFileSync(file, 'utf8');
  if (!s.includes(from)) {
    console.error('help text not found in', name);
    process.exitCode = 1;
    continue;
  }
  fs.writeFileSync(file, s.replace(from, to));
  console.log('Patched help in', name);
}
