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
// index.html is scanned too: its inline <style> and <script> blocks can animate as well.
const found = (): Violation[] => [
  ...files.flatMap((f) => scanSource(`src/${f}`, readFileSync(join(SRC, f), "utf8"))),
  ...scanSource("index.html", readFileSync(join(SRC, "..", "index.html"), "utf8")),
];
const allowed = (v: Violation) => ALLOWLIST.some((a) => a.file === v.file && a.rule === v.rule);

// The scans read every source file; under a full parallel run they outlast vitest's 5 s default (#290).
const SCAN_TIMEOUT_MS = 30_000;

describe(
  "FR_WLD_09 static check: no animation outside the choreographer (HR-1, HR-2, HR-3)",
  { timeout: SCAN_TIMEOUT_MS },
  () => {
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
      // The two choreographer-era clocks plus the Park city's ambient entries (WEB-MOTION-1: four, city layer only).
      // Updated for WEB-MOTION-2: cap 6 -> 7, the one css-transition entry for the shell's own chrome.
      // LANDING-2: one more, the landing's css-transition (landing.motion.css).
      // TILO-T-FOUNDATION: three more, all in src/design/tilo-t/motion.css (keyframes, animation, the reduced-motion transition).
      expect(ALLOWLIST.length).toBeLessThanOrEqual(11);
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

    it("FR_WLD_09 app CSS has no keyframes, animation, transition or smooth scrolling outside the allowlist", () => {
      // Only the Park city's ambient keyframes and pause rule (park.shell.css) are on the allowlist.
      const css = found().filter((v) => v.file.endsWith(".css") && !allowed(v));
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
  },
);

describe(
  "FR_WLD_09 the scanner itself catches each kind of animation",
  { timeout: SCAN_TIMEOUT_MS },
  () => {
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
      ["src/x.ts", "el.style.transition = 'opacity 1s';", "style-assign-motion"],
      ["src/x.ts", "el.style.animationName = 'spin';", "style-assign-motion"],
      ["src/x.ts", "el.style.setProperty('transition', 'all 1s');", "style-assign-motion"],
      ["src/x.ts", "el['animate']([{ opacity: 0 }], 200);", "waapi-bracket"],
      ["src/x.ts", 'el["animate"]([{ opacity: 0 }], 200);', "waapi-bracket"],
      ["src/x.ts", "el\n  .animate(\n    [{ opacity: 0 }],\n    200,\n  );", "waapi"],
      ["src/x.ts", "el.animate\n(keyframes, 200);", "waapi"],
      ["src/x.ts", "el?.animate(keyframes, 200);", "waapi"],
      ["src/x.ts", "el.scrollIntoView({ behavior: 'smooth' });", "smooth-scroll-js"],
      ["src/x.ts", 'window.scrollTo({ top: 0, behavior: "smooth" });', "smooth-scroll-js"],
      ["src/x.ts", "requestIdleCallback(work);", "raf"],
      ["src/x.ts", "const m = await import('framer-motion');", "tween-library"],
      ["src/x.ts", "import 'gsap';", "tween-library"],
      ["src/x.ts", "import { motion } from 'motion/react';", "tween-library"],
      ["src/x.tsx", "const css = `@keyframes spin { to { opacity: 0; } }`;", "css-keyframes"],
      ["src/x.tsx", "const css = `.a { transition: opacity 1s; }`;", "css-transition"],
      ["index.html", "<style>.a { animation: spin 1s infinite; }</style>", "css-animation"],
      ["index.html", "<style>@keyframes spin { to { opacity: 0; } }</style>", "css-keyframes"],
      ["index.html", "<script>requestAnimationFrame(tick);</script>", "raf"],
      ["index.html", "<script>setInterval(tick, 16)</script>", "interval"],
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

    // The comment stripper must not be fooled by comment markers inside strings, templates or regexes.
    it.each([
      ["// inside a string", "const u = 'x//'; requestAnimationFrame(f);"],
      ["// inside a double-quoted string", 'const u = "a//b"; setInterval(f, 1);'],
      ["/* inside a string", 'const s = "/*"; requestAnimationFrame(f); const t = "*/";'],
      ["/* inside a string, then a real comment", "const s = '/*'; el.animate(k, 1); /* c */"],
      ["// inside a template", "const u = `x//y`; requestAnimationFrame(f);"],
      ["code inside a template expression", "const u = `// ${requestAnimationFrame(f)} //`;"],
      ["code after a nested template", "const u = `a${`b//`}c`; requestAnimationFrame(f);"],
      ["// inside a regex", "const r = /\\/\\//; requestAnimationFrame(f);"],
      ["a quote inside a regex", "const r = /'/; requestAnimationFrame(f);"],
      ["a quote inside a regex class", "const r = /[/']/; requestAnimationFrame(f);"],
      ["an apostrophe in JSX text", "const a = <p>don't</p>;\nrequestAnimationFrame(f);"],
      ["a closing JSX tag before a comment", "const a = <p>x</p>; // note\nsetInterval(f, 1);"],
      ["code before a trailing comment", "requestAnimationFrame(f); // fine"],
      ["division before a block comment", "const q = a / b; /* c */ setInterval(f, 1);"],
    ])("FR_WLD_09 comment stripping: still scans real code after %s", (_name, code) => {
      expect(scanSource("src/x.tsx", code).length).toBeGreaterThan(0);
    });

    it.each([
      ["a line comment", "// requestAnimationFrame(f)\nconst a = 1;"],
      ["a block comment across lines", "/* setInterval\n el.animate( */ const a = 1;"],
      ["a trailing comment", "const a = 1; // el.animate(k, 1)"],
      ["a comment after a string with //", "const u = 'http://x'; // requestAnimationFrame(f)"],
      ["a JSDoc block", "/** uses requestAnimationFrame */\nexport const a = 1;"],
    ])("FR_WLD_09 comment stripping: ignores %s", (_name, code) => {
      expect(scanSource("src/x.ts", code)).toEqual([]);
    });

    it("FR_WLD_09 a CSS string holding a comment marker does not hide rules; html comments are ignored", () => {
      const css = '.a::after { content: "/*"; transition: opacity 1s; } /* c */';
      expect(rulesHit("src/x.css", css)).toContain("css-transition");
      expect(scanSource("index.html", "<!-- <style>.a{animation:x 1s}</style> -->")).toEqual([]);
    });

    it("FR_WLD_09 reports the right line for a multi-line match and for code after a string marker", () => {
      expect(scanSource("src/x.ts", "a;\nb;\nel\n.animate(\nk)").map((v) => v.line)).toEqual([4]);
      expect(
        scanSource("src/x.ts", "const s = '/*';\nsetInterval(f, 1);").map((v) => v.line),
      ).toEqual([2]);
    });
  },
);
