// X-PERF-1: run after `vite build --manifest`. Count entry, Park shell and Home
// plus every static dependency once. Dynamic route imports are not Home loads.
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";

const dist = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", dist), "utf8"));
const loaded = new Set();
function visit(key) {
  assert.ok(manifest[key], `Missing build chunk: ${key}`);
  if (loaded.has(key)) return;
  loaded.add(key);
  for (const dependency of manifest[key].imports ?? []) visit(dependency);
}
visit("index.html");
for (const name of ["ParkApp", "HomePage"]) {
  const key = Object.keys(manifest).find(
    (key) => manifest[key].name === name && manifest[key].isDynamicEntry,
  );
  assert.ok(key, `Missing ${name} route entry`);
  visit(key);
}
const files = [...loaded].map((key) => manifest[key].file);
assert.ok(
  !files.some((file) => /WorldPage|ParticleBuffer|pixi/i.test(file)),
  "World/Pixi must stay outside the initial Home graph",
);
const bytes = files.reduce((sum, file) => sum + statSync(new URL(file, dist)).size, 0);
// c1a4394d boot fetched 719,820 bytes including automatic eight-page prefetch.
// Its required Home graph was 402,135 bytes. Keep a small compiler margin and
// protect the >20% reduction without hiding required Home dependencies.
assert.ok(bytes <= 410_000, `X-PERF-1 Home JS ${bytes} exceeds 410000 bytes`);
console.log(`X-PERF-1 Home JS budget PASS: ${bytes}/410000 bytes`);
