const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(__dirname + "/index.js", "utf8");
const begin = source.indexOf("function japanTime(");
const end = source.indexOf("async function oneTimeSelfTest(");
assert(begin >= 0 && end > begin, "Missing time-window functions");
const context = { Date, Intl, Number };
vm.createContext(context);
vm.runInContext(source.slice(begin, end) + "\nthis.monitoringWindow = monitoringWindow;", context);
const cases = [
  ["2026-11-12T14:59:00Z", true, "business_hours"], // 23:59 JST
  ["2026-11-12T15:00:00Z", false, "night_rest"],     // 00:00 JST
  ["2026-11-12T22:59:00Z", false, "night_rest"],     // 07:59 JST
  ["2026-11-12T23:00:00Z", false, "morning_grace"],  // 08:00 JST
  ["2026-11-12T23:14:00Z", false, "morning_grace"],  // 08:14 JST
  ["2026-11-12T23:15:00Z", true, "business_hours"],  // 08:15 JST
  ["2026-11-13T14:59:00Z", true, "business_hours"],
  ["2026-12-28T15:00:00Z", false, "official_holiday"], // Dec 29 JST
  ["2027-01-03T14:00:00Z", false, "official_holiday"], // Jan 3 JST
  ["2027-01-03T23:15:00Z", true, "business_hours"]    // Jan 4 JST
];
for (const [time, enabled, reason] of cases) {
  const actual = context.monitoringWindow(Date.parse(time));
  assert.equal(actual.enabled, enabled, time);
  assert.equal(actual.reason, reason, time);
}
console.log("PASS: " + cases.length + " JST scheduling edge cases");
