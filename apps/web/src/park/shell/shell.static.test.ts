// WEB-3b static checks over apps/web/src/park/shell (plan sections 6, 8d, 10; root CLAUDE.md):
// - AppShell.tsx and park.shell.css exist, AppShell loads the stylesheet, ParkApp renders AppShell;
// - the honesty scan finds nothing beyond the city's allowlisted entries (WEB-MOTION-1: ambient cars and
//   walkers, BQ-WEB-3); no transition / animation / rAF / interval in the shell's code, and no timer of the shell's
//   own: the loader runs on the store's injected scheduler;
// - no window globals, any, ts-ignore, raw HTML, model ids or support.js;
// - only router.ts touches window.location under park/ (the WEB-3a rule);
// - imports come from react and park/ only, nothing from screens, world or stage.
// Test files are excluded from the walk (they name these patterns on purpose).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../test-support/honestyScan";

const SHELL = __dirname;
const PARK = resolve(SHELL, "..");
const rel = (base: string, p: string) => relative(base, p).replaceAll("\\", "/");
const text = (p: string) => readFileSync(p, "utf8");
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.test\.tsx?$/.test(name) ? [] : [p];
  });
}

const files = walk(SHELL);
const sources = files.filter((p) => /\.(tsx?|css)$/.test(p));
const ts = files.filter((p) => /\.tsx?$/.test(p));
const shellRel = (p: string) => rel(SHELL, p);

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_3b_static: the shell exists and is wired", () => {
  it("WEB_3b_static_AppShell_and_its_one_stylesheet_are_there", () => {
    const have = files.map(shellRel);
    expect(have).toContain("AppShell.tsx");
    expect(have).toContain("park.shell.css");
  });

  it("WEB_3b_static_a_shell_component_imports_the_stylesheet", () => {
    expect(
      ts.some((p) => /import\s+["']\.\/park\.shell\.css["']/.test(code(p))),
      "no shell file imports ./park.shell.css",
    ).toBe(true);
  });

  it("WEB_3b_static_ParkApp_renders_AppShell", () => {
    const app = code(join(PARK, "app", "ParkApp.tsx"));
    expect(app).toMatch(/from\s+["']\.\.\/shell\/AppShell["']/);
    expect(app).toMatch(/<AppShell\b/);
  });
});

describe("WEB_3b_static: honesty (HR-1..HR-7; the scan and its allowlist, WEB-MOTION-1 edit)", () => {
  it("WEB_3b_static_ALLOWLIST_has_only_the_two_choreographer_clocks_and_the_city_layer_entries", () => {
    // WEB-MOTION-1 added the city's ambient entries (engines/park.ts and shell/park.shell.css only).
    // Updated for WEB-MOTION-2: exactly one more, the shell stylesheet's css-transition (splash, page swap, bar).
    expect(ALLOWLIST.map((e) => `${e.file}:${e.rule}`)).toEqual([
      "src/world/runWorld.ts:raf",
      "src/stage/Stage.tsx:raf",
      "src/park/engines/park.ts:inline-motion-style",
      "src/park/engines/park.ts:css-animation",
      "src/park/shell/park.shell.css:css-keyframes",
      "src/park/shell/park.shell.css:css-animation",
      "src/park/shell/park.shell.css:css-transition",
      "src/landing/landing.motion.css:css-transition", // LANDING-2
    ]);
  });

  it("WEB_3b_static_the_honesty_scan_finds_nothing_in_park_shell_but_the_allowlisted_city_css", () => {
    expect(sources.length).toBeGreaterThanOrEqual(2);
    const hits = sources
      .flatMap((p) => scanSource(`src/park/shell/${shellRel(p)}`, text(p)))
      .filter((v) => !ALLOWLIST.some((a) => a.file === v.file && a.rule === v.rule));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_3b_static_no_transition_animation_keyframes_raf_or_animate_call", () => {
    // The shell's code starts no animation; only park.shell.css holds the city's keyframes and pause rule.
    const banned =
      /\btransition\b|\banimation\b|@keyframes|requestAnimationFrame|cancelAnimationFrame|\.animate\s*\(/;
    expect(ts.filter((p) => banned.test(code(p))).map(shellRel)).toEqual([]);
    // Updated for WEB-MOTION-2: the stylesheet may now hold transitions (transform and opacity only, pinned in
    // motion.transitions.css.test.ts); it still holds no frame loop or script animation.
    const cssBanned = /requestAnimationFrame|\.animate\s*\(/;
    expect(
      sources.filter((p) => p.endsWith(".css") && cssBanned.test(code(p))).map(shellRel),
    ).toEqual([]);
  });

  it("WEB_3b_static_the_shell_starts_no_timer_of_its_own", () => {
    const timers = /\b(?:setTimeout|setInterval|clearTimeout|clearInterval)\b/;
    expect(ts.filter((p) => timers.test(code(p))).map(shellRel)).toEqual([]);
  });
});

describe("WEB_3b_static: code hygiene", () => {
  it("WEB_3b_static_no_window_global_is_assigned", () => {
    const hits = sources.flatMap((p) =>
      code(p)
        .split(/\r?\n/)
        .map((line, i) => ({ file: shellRel(p), line: i + 1, text: line.trim() }))
        .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text)))
        .map((l) => `${l.file}:${l.line} ${l.text}`),
    );
    expect(hits).toEqual([]);
  });

  it("WEB_3b_static_no_any_no_ts_ignore_no_raw_html_no_dynamic_code", () => {
    const bad = {
      any: /:\s*any\b|\bas\s+any\b|<any>|\bany\[\]|Array<any>|Record<[^>]*\bany\b/,
      tsIgnore: /@ts-ignore|@ts-nocheck/,
      html: /dangerouslySetInnerHTML|\.innerHTML\s*=|\binsertAdjacentHTML\b/,
      dyn: /\beval\s*\(|new\s+Function\s*\(/,
    };
    for (const [name, re] of Object.entries(bad)) {
      expect(ts.filter((p) => re.test(text(p))).map(shellRel), name).toEqual([]);
    }
  });

  it("WEB_3b_static_no_model_id_and_no_support_js", () => {
    expect(sources.filter((p) => MODEL_ID.test(text(p))).map(shellRel)).toEqual([]);
    expect(files.filter((p) => /support\.js/i.test(text(p))).map(shellRel)).toEqual([]);
  });

  it("WEB_3b_static_only_router_ts_touches_window_location_or_history_under_park", () => {
    const hits = walk(PARK)
      .filter((p) => /\.tsx?$/.test(p))
      .filter((p) => rel(PARK, p) !== "app/router.ts")
      .filter((p) =>
        /\bwindow\s*\.\s*location\b|\bdocument\s*\.\s*location\b|\bwindow\s*\.\s*history\b|\bhistory\s*\.\s*(?:push|replace)State\b|\blocation\s*\.\s*(?:pathname|search|href|hash)\b/.test(
          code(p),
        ),
      )
      .map((p) => rel(PARK, p));
    expect(hits).toEqual([]);
  });
});

describe("WEB_3b_static: imports", () => {
  const importsOf = (p: string): string[] =>
    [...code(p).matchAll(/(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] ?? "");

  it("WEB_3b_static_the_shell_imports_only_react_and_park", () => {
    const bad: string[] = [];
    for (const p of ts) {
      for (const spec of importsOf(p)) {
        if (!spec.startsWith(".")) {
          if (!/^react(\/|$)|^react-dom(\/|$)/.test(spec))
            bad.push(`${shellRel(p)} imports ${spec}`);
          continue;
        }
        // SEC-16: the one shared lifetime-cap dialog (src/components/LifetimeCapDialog) is the only import from outside park.
        const target = resolve(dirname(p), spec);
        if (
          !target.startsWith(PARK) &&
          target !== resolve(PARK, "..", "components", "LifetimeCapDialog")
        )
          bad.push(`${shellRel(p)} imports ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("WEB_3b_static_nothing_from_screens_world_or_stage", () => {
    const bad = ts.filter((p) =>
      importsOf(p).some((s) => /(^|\/)(screens|world|stage)(\/|$)/.test(s)),
    );
    expect(bad.map(shellRel)).toEqual([]);
  });
});
