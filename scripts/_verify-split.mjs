import fs from "node:fs";

const s = fs.readFileSync("new_frontend/app.bundle.js", "utf8");
const t = s.indexOf("emuPage==='top'");
const m = s.indexOf("emuPage==='top_meta'", t);
const top = s.slice(t, m);
const meta = s.slice(m, s.indexOf("function EmuBroadcastScreen", m));

console.log("p3 sync", top.includes("syncProfilesFromDashboard"));
console.log("p3 TOP MOVERS", top.includes("TOP MOVERS"));
console.log("p3 platforms", top.includes("NF_EMU_PLATFORM_IDS"));
console.log("p4 sync", meta.includes("syncProfilesFromDashboard"));
console.log("p4 TOP MOVERS", meta.includes("TOP MOVERS"));
console.log("p4 platforms", meta.includes("NF_EMU_PLATFORM_IDS"));
