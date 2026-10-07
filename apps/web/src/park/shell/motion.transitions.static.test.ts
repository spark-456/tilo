// WEB-MOTION-2 static checks (PRD 9.4 HR-1 to HR-7; honesty scan; README "Performance"): the boot, page and loader
// motion is written in the shell stylesheet and driven by state and the store's injected scheduler, never by a
// frame loop, a repeating timer, Element.animate, a view transition, a tween library or an inline style that
// starts motion. Any of those would need a honesty-scan exception of its own (src/honesty/park-transitions.allowlist.test.ts
// allows exactly one new, stylesheet-only entry). Test files are left out of the walk.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const PARK = join(__dirname, "..");
const AREAS = ["shell", "app"] as const;

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [p] : [];
  });
}
const code = (p: string): string =>
  readFileSync(p, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const files = AREAS.flatMap((a) => walk(join(PARK, a)));
const rel = (p: string): string => relative(PARK, p).replaceAll("\\", "/");
const offenders = (re: RegExp): string[] => files.filter((p) => re.test(code(p))).map(rel);

describe("WEB-MOTION-2 static: chrome motion starts from state, in the stylesheet, with no loop", () => {
  it("WEB-MOTION-2 static: the shell and the app code start no frame loop, no repeating timer, no Element.animate and no view transition", () => {
    expect(files.length).toBeGreaterThan(10);
    expect(
      offenders(/\b(?:request|cancel)AnimationFrame\b|\b(?:request|cancel)IdleCallback\b/),
    ).toEqual([]);
    expect(offenders(/\bsetInterval\s*\(|\bclearInterval\s*\(/)).toEqual([]);
    expect(offenders(/\.\s*animate\s*\(|\[\s*["'`]animate["'`]\s*\]/)).toEqual([]);
    expect(offenders(/startViewTransition|view-transition/)).toEqual([]);
  });

  it("WEB-MOTION-2 static: no tween library, no inline transition or animation style, no smooth scroll in the shell and the app code", () => {
    expect(
      offenders(
        /\b(?:from|import|require)\s*\(?\s*["'](?:gsap|animejs?|popmotion|motion|framer-motion|react-spring|@react-spring\/[\w-]+|react-transition-group)["'/]/,
      ),
    ).toEqual([]);
    expect(offenders(/\b(?:transition|animation)(?:[A-Z]\w*)?\s*:/)).toEqual([]);
    expect(
      offenders(
        /\.style\s*\.\s*(?:transition|animation)\w*\s*=|setProperty\s*\(\s*["'](?:transition|animation)/,
      ),
    ).toEqual([]);
    expect(offenders(/behavior\s*:\s*["']smooth["']/)).toEqual([]);
  });
});
