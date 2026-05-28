import fs from "node:fs";

const s = fs.readFileSync("new_frontend/app.bundle.js", "utf8");
const start = s.indexOf('return/*#__PURE__*/React.createElement("div"', s.indexOf("function EmuSettingsScreen"));
const end = s.indexOf("function EmuBroadcastScreen", start);
const chunk = s.slice(start, end);

let depth = 0;
let inStr = null;
let esc = false;
for (let i = 0; i < chunk.length; i++) {
  const c = chunk[i];
  if (inStr) {
    if (esc) {
      esc = false;
      continue;
    }
    if (c === "\\") {
      esc = true;
      continue;
    }
    if (c === inStr) inStr = null;
    continue;
  }
  if (c === '"' || c === "'" || c === "`") {
    inStr = c;
    continue;
  }
  if (c === "(") depth++;
  if (c === ")") depth--;
}

console.log("paren depth at end of return chunk:", depth);
console.log("last 80 chars:", JSON.stringify(chunk.slice(-80)));
