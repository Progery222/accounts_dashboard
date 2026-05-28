import { execSync } from "node:child_process";
import fs from "node:fs";

execSync("node scripts/restore-emu-settings-from-head.mjs", { stdio: "inherit" });

let s = fs.readFileSync("new_frontend/app.bundle.js", "utf8");
const reps = [
  ['")),),emuPage===\'pulse\'', '"))),emuPage===\'pulse\''],
  [
    "allowNegativeValues:true})),),emuPage==='top'",
    "allowNegativeValues:true}))),emuPage==='top'",
  ],
];
for (const [from, to] of reps) {
  const n = s.split(from).length - 1;
  if (!n) throw new Error(`pattern missing: ${from}`);
  s = s.split(from).join(to);
  console.log("fixed", from.slice(0, 40), "x", n);
}
fs.writeFileSync("new_frontend/app.bundle.js", s, "utf8");
console.log("done");
