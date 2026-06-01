import fs from 'node:fs';

const bundlePath = 'new_frontend/app.bundle.js';
let s = fs.readFileSync(bundlePath, 'utf8');

const tail = 'TV (BROADCAST),/*#__PURE__*/React.createElement("input"';
const idx = s.indexOf(tail);
if (idx < 0) throw new Error('BROADCAST label snippet not found');

const labelStart = s.lastIndexOf('}},', idx);
if (labelStart < 0 || idx - labelStart > 120) {
  throw new Error(`unexpected context: ${JSON.stringify(s.slice(labelStart, idx + tail.length))}`);
}

const labelText = s.slice(labelStart + 3, idx + 'TV (BROADCAST)'.length);
const replacement = `"${labelText}",/*#__PURE__*/React.createElement("input"`;
s = s.slice(0, labelStart + 3) + replacement + s.slice(idx + tail.length);

fs.writeFileSync(bundlePath, s, 'utf8');
console.log('fixed:', JSON.stringify(labelText));
