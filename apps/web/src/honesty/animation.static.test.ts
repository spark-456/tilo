// FR-WLD-09 (PRD 9.4 HR-1 to HR-3): static check, "no animation outside the choreographer".
// Scans every non-test source file under apps/web/src for animation APIs and fails on any use that
// is not on the explicit allowlist in test-support/honestyScan.ts (each entry carries its reason).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ALLOWLIST,
  BANNED_PACKAGES,
  RULES,
  type Violation,
  scanSource,
} from "../../test-support/honestyScan";

const SRC = join(__dirname, "..");
const SKIP_DIR = new Set(["fonts", "node_modules"]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return SKIP_DIR.has(name) ? [] : walk(p);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) && !/\.generated\./.test(name)
      ? [p]
      : [];
  });
}

const files = walk(SRC).map((p) => relative(SRC, p).replaceAll("\\", "/"));
const found = (): Violation[] =>
  files.flatMap((f) => scanSource(`src/${f}`, readFileSync(join(SRC, f), "utf8")));
const allowed = (v: Violation) => ALLOWLIST.some((a) => a.file === v.file && a.rule === v.rule);

describe("FR_WLD_09 static check: no animation outside the choreographer (HR-1, HR-2, HR-3)", () => {
  it("FR_WLD_09 finds source files to scan (the check is not vacuous)", () => {
    expect(files).toContain("world/choreographer.ts");
    expect(files).toContain("styles/app.css");
    expect(files.length).toBeGreaterThan(40);
  });

  it("FR_WLD_09 no animation API is used outside the allowlist", () => {
    const stray = found().filter((v) => !allowed(v));
    expect(
      stray.map((v) => `${v.file}:${v.line} ${v.rule}: ${v.text}`),
      "animation outside the choreographer; route it through world/choreographer.ts or allowlist it with a reason in test-support/honestyScan.ts",
    ).toEqual([]);
  });

  it("FR_WLD_09 the allowlist is small, every entry has a reason, and none is stale", () => {
    expect(ALLOWLIST.length).toBeLessThanOrEqual(3);
    const hits = found();
    for (const a of ALLOWLIST) {
      expect(a.reason.length, `${a.file} needs a reason`).toBeGreaterThanOrEqual(30);
      expect(
        hits.some((v) => v.file === a.file && v.rule === a.rule),
        `${a.file} no longer uses ${a.rule}: remove the allowlist entry`,
      ).toBe(true);
    }
  });

  it("FR_WLD_09 the choreographer is the only module that owns timed world motion", () => {
    expect(ALLOWLIST.some((a) => a.file === "src/world/choreographer.ts")).toBe(false);
  });

  it("FR_WLD_09 app CSS has no keyframes, animation, transition or smooth scrolling at all", () => {
    const css = found().filter((v) => v.file.endsWith(".css"));
    expect(css).toEqual([]);
  });

  it("FR_WLD_09 no animation library is a dependency of the web app", () => {
    const pkg = JSON.parse(readFileSync(join(SRC, "..", "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const names = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(names.filter((n) => BANNED_PACKAGES.test(n))).toEqual([]);
  });
});

describe("FR_WLD_09 the scanner itself catches each kind of animation", () => {
  const rulesHit = (file: string, code: string) => scanSource(file, code).map((v) => v.rule);
  it.each([
    ["src/x.ts", "const id = requestAnimationFrame(tick);", "raf"],
    ["src/x.ts", "setInterval(() => spin(), 16);", "interval"],
    ["src/x.ts", "el.animate([{ opacity: 0 }, { opacity: 1 }], 300);", "waapi"],
    ["src/x.ts", "app.ticker.add(update);", "pixi-ticker"],
    ["src/x.ts", "import { Ticker } from 'pixi.js';", "pixi-ticker"],
    ["src/x.ts", "import { gsap } from 'gsap';", "tween-library"],
    ["src/x.tsx", "<div style={{ transition: 'all 1s' }} />", "inline-motion-style"],
    ["src/x.tsx", "<animateTransform attributeName='transform' />", "smil"],
    ["src/x.ts", "document.startViewTransition(() => go());", "view-transition"],
    ["src/x.css", "@keyframes spin { to { transform: rotate(1turn); } }", "css-keyframes"],
    ["src/x.css", ".a { animation: spin 1s infinite; }", "css-animation"],
    ["src/x.css", ".a { transition: opacity 0.2s; }", "css-transition"],
    ["src/x.css", "html { scroll-behavior: smooth; }", "css-smooth-scroll"],
  ])("FR_WLD_09 flags %s: %s", (file, code, rule) => {
    expect(rulesHit(file, code)).toContain(rule);
  });

  it("FR_WLD_09 ignores comments and every rule has a name and a reason to exist", () => {
    expect(
      scanSource("src/x.ts", "// requestAnimationFrame is not used\n/* setInterval */"),
    ).toEqual([]);
    expect(scanSource("src/x.css", "/* transition: none */")).toEqual([]);
    for (const r of RULES) expect(r.why.length).toBeGreaterThan(10);
  });
});
