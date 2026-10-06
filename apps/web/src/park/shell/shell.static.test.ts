// WEB-3b static checks over apps/web/src/park/shell (plan sections 6, 10; root CLAUDE.md):
// - the files of the shell exist (names and exports pinned by the component tests);
// - the honesty scan finds nothing and its ALLOWLIST is unchanged (the allowlist edit comes with the motion
//   restore, BQ-WEB-3); no transition / animation / keyframes / rAF / timers: the loader is driven by the
//   store's injected scheduler (WEB-3a), never by a timer of the shell;
// - no window globals, any, ts-ignore, raw HTML, model ids or support.js;
// - only router.ts touches window.location, anywhere under park/ (the 3a rule, unchanged);
// - imports come from react and park/ only; the stylesheet is imported by AppShell; ParkApp wears the shell.
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

describe("WEB_3b_static: the shell files exist", () => {
  it("WEB_3b_static_the_pinned_files_are_there", () => {
    const have = files.map(shellRel);
    for (const f of [
      "AppShell.tsx",
      "TopNav.tsx",
      "NotificationsPopover.tsx",
      "AccountMenu.tsx",
      "CityBackdrop.tsx",
      "WorldLoader.tsx",
      "BootSplash.tsx",
      "sceneCache.ts",
      "pins.ts",
      "park.shell.css",
    ]) {
      expect(have, `${f} is missing`).toContain(f);
    }
  });

  it("WEB_3b_static_AppShell_imports_the_stylesheet_and_ParkApp_renders_AppShell", () => {
    expect(code(join(SHELL, "AppShell.tsx"))).toMatch(/import\s+["']\.\/park\.shell\.css["']/);
    const app = code(join(PARK, "app", "ParkApp.tsx"));
    expect(app).toMatch(/from\s+["']\.\.\/shell\/AppShell["']/);
    expect(app).toMatch(/<AppShell\b/);
  });

  it("WEB_3b_static_ParkApp_no_longer_renders_a_main_of_its_own", () => {
    expect(code(join(PARK, "app", "ParkApp.tsx"))).not.toMatch(/<main\b/);
    expect(code(join(SHELL, "AppShell.tsx"))).toMatch(/<main\b/);
  });
});

describe("WEB_3b_static: honesty (HR-1..HR-7; the scan and its allowlist are untouched)", () => {
  it("WEB_3b_static_ALLOWLIST_is_unchanged", () => {
    expect(ALLOWLIST.map((e) => `${e.file}:${e.rule}`)).toEqual([
      "src/world/runWorld.ts:raf",
      "src/stage/Stage.tsx:raf",
    ]);
  });

  it("WEB_3b_static_the_honesty_scan_finds_nothing_in_park_shell", () => {
    expect(sources.length).toBeGreaterThanOrEqual(10);
    const hits = sources.flatMap((p) => scanSource(`src/park/shell/${shellRel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_3b_static_no_transition_animation_keyframes_raf_or_animate_call", () => {
    const banned =
      /\btransition\b|\banimation\b|@keyframes|requestAnimationFrame|cancelAnimationFrame|\.animate\s*\(/;
    expect(sources.filter((p) => banned.test(code(p))).map(shellRel)).toEqual([]);
  });

  it("WEB_3b_static_the_shell_starts_no_timer_of_its_own", () => {
    const timers = /\b(?:setTimeout|setInterval|clearTimeout|clearInterval|queueMicrotask)\b/;
    expect(ts.filter((p) => timers.test(code(p))).map(shellRel)).toEqual([]);
  });

  it("WEB_3b_static_inline_styles_never_name_a_transition_or_animation", () => {
    const hits = ts.filter((p) => /["'`]\s*(?:transition|animation)[A-Za-z]*\s*["'`]\s*:/.test(code(p)));
    expect(hits.map(shellRel)).toEqual([]);
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

  it("WEB_3b_static_navigation_goes_through_the_store_never_a_raw_href_assignment", () => {
    expect(ts.filter((p) => /\.href\s*=(?!=)/.test(code(p))).map(shellRel)).toEqual([]);
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
          if (!/^react(\/|$)|^react-dom(\/|$)/.test(spec)) bad.push(`${shellRel(p)} imports ${spec}`);
          continue;
        }
        const target = resolve(dirname(p), spec);
        if (!target.startsWith(PARK)) bad.push(`${shellRel(p)} imports ${spec}`);
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

  it("WEB_3b_static_the_engines_are_reached_from_the_shell_not_from_the_pages", () => {
    // the backdrop and the loader art come from engines/ (createPark, createKit), never from a copy
    const all = ts.map((p) => importsOf(p).join(" ")).join(" ");
    expect(all).toMatch(/\.\.\/engines\//);
  });
});
