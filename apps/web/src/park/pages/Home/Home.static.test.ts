// WEB-4 static checks over apps/web/src/park/pages/Home (plan sections 6 and 10; root CLAUDE.md hard rules):
// - the page folder holds HomePage.tsx (named export HomePage) and Home.css; the registry has one line for it;
// - data only through useParkApi (no fixture or live Api import, no fetch), navigation only through app.go
//   (no address-bar reads), the 900 ms only through useSchedule (no setTimeout, no interval, no rAF);
// - no transition / animation / keyframes, no `any`, no @ts-ignore, no window assignment, no raw HTML, no
//   model id, no support.js; imports only react, park/components, park/engines, park/api and park/app;
// - nothing from screens/, world/, stage/ or another page; the honesty scan finds nothing; ALLOWLIST unchanged.
// Test files are excluded from the walk (they name these patterns on purpose).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../../test-support/honestyScan";

// The Park city's ambient scenery (shell and engines) is decoration, not work: its animation entries are
// pinned by src/honesty/park-ambient.allowlist.test.ts. Every other entry stays pinned exactly here.
const AMBIENT = /^src\/park\/(shell|engines)\//;

const HOME = __dirname;
const PAGES = resolve(HOME, "..");
const PARK = resolve(PAGES, "..");
const SRC = resolve(PARK, "..");

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.test\.tsx?$/.test(name) ? [] : [p];
  });
}
const text = (p: string) => readFileSync(p, "utf8");
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const rel = (p: string) => relative(HOME, p).replaceAll("\\", "/");

const files = walk(HOME);
const sources = files.filter((p) => /\.(tsx?|css)$/.test(p));
const ts = files.filter((p) => /\.tsx?$/.test(p));

// Every check below walks the page's own files: with no page there is nothing to pass vacuously.
beforeEach(() => {
  expect(ts.map(rel), "src/park/pages/Home/HomePage.tsx is missing").toContain("HomePage.tsx");
});

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_4_static: the page folder", () => {
  it("WEB_4_static_the_folder_holds_HomePage_tsx_and_Home_css", () => {
    const names = files.map(rel);
    expect(names).toContain("HomePage.tsx");
    expect(names).toContain("Home.css");
  });

  it("WEB_4_static_HomePage_is_a_named_export_taking_app", () => {
    const src = code(join(HOME, "HomePage.tsx"));
    expect(src).toMatch(/export\s+(?:function|const)\s+HomePage\b/);
  });

  it("WEB_4_static_pages_ts_gains_one_line_for_home_and_keeps_the_other_eight", () => {
    const src = readFileSync(join(PARK, "app", "pages.ts"), "utf8");
    const homeLines = src.split(/\r?\n/).filter((l) => /^\s*home\s*:/.test(l));
    expect(homeLines).toHaveLength(1);
    expect(homeLines[0]).toMatch(/pages\/Home\/HomePage/);
    expect(homeLines[0]).not.toMatch(/Placeholder/);
    for (const id of [
      "worlds",
      "world",
      "skills",
      "ledger",
      "agenda",
      "team",
      "profile",
      "connectors",
    ]) {
      expect(src.split(/\r?\n/).filter((l) => new RegExp(`^\\s*${id}\\s*:`).test(l))).toHaveLength(
        1,
      );
    }
  });
});

describe("WEB_4_static: honesty (HR-1..HR-7; the scan and its allowlist are untouched)", () => {
  it("WEB_4_static_ALLOWLIST_is_unchanged", () => {
    expect(
      ALLOWLIST.filter((e) => !AMBIENT.test(e.file)).map((e) => `${e.file}:${e.rule}`),
    ).toEqual(["src/world/runWorld.ts:raf", "src/stage/Stage.tsx:raf"]);
  });

  it("WEB_4_static_the_honesty_scan_finds_nothing_in_the_page", () => {
    expect(sources.length).toBeGreaterThanOrEqual(2);
    const hits = sources.flatMap((p) => scanSource(`src/park/pages/Home/${rel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_4_static_no_transition_animation_keyframes_raf_interval_or_setTimeout", () => {
    const banned =
      /\btransition\b|\banimation\b|@keyframes|requestAnimationFrame|cancelAnimationFrame|setInterval|setTimeout|clearTimeout|\.animate\s*\(/;
    expect(sources.filter((p) => banned.test(code(p))).map(rel)).toEqual([]);
  });

  it("WEB_4_static_the_composer_delay_goes_through_useSchedule", () => {
    const src = code(join(HOME, "HomePage.tsx"));
    expect(src).toMatch(/\buseSchedule\b/);
    // the 900 ms is homeData's DRAFT_MS, scheduled by the page (UI-STUDIO-2 dropped the viewport literal that matched)
    expect(src).toMatch(/schedule\([\s\S]*?DRAFT_MS\)/);
    expect(code(join(HOME, "homeData.ts"))).toMatch(/DRAFT_MS = 900\b/);
  });
});

describe("WEB_4_static: data and navigation seams", () => {
  it("WEB_4_static_data_only_through_useParkApi", () => {
    const src = code(join(HOME, "HomePage.tsx"));
    expect(src).toMatch(/\buseParkApi\b/);
    for (const p of ts) {
      expect(code(p), rel(p)).not.toMatch(
        /api\/fixtures|fixtureApi|createFixtureApi|liveApi|createLiveApi|parkApi\b|\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource/,
      );
    }
  });

  it("WEB_4_static_navigation_only_through_app_go_no_address_bar_reads", () => {
    expect(code(join(HOME, "HomePage.tsx"))).toMatch(/\bapp\.go\(|\bgo\(/);
    const hits = ts.filter((p) =>
      /\bwindow\s*\.\s*location\b|\bdocument\s*\.\s*location\b|\bwindow\s*\.\s*history\b|\bhistory\s*\.\s*(?:push|replace)State\b|\blocation\s*\.\s*(?:pathname|search|href|hash|assign|replace)\b|\bnavigatePark\b|\bparkPath\b/.test(
        code(p),
      ),
    );
    expect(hits.map(rel)).toEqual([]);
  });

  it("WEB_4_static_approvals_are_not_made_on_home", () => {
    expect(ts.filter((p) => /\.decide\(|\bdecide\s*\(/.test(code(p))).map(rel)).toEqual([]);
  });
});

describe("WEB_4_static: code hygiene", () => {
  it("WEB_4_static_no_window_global_is_assigned", () => {
    const hits = sources.flatMap((p) =>
      code(p)
        .split(/\r?\n/)
        .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
        .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text)))
        .map((l) => `${l.file}:${l.line} ${l.text}`),
    );
    expect(hits).toEqual([]);
  });

  it("WEB_4_static_no_any_no_ts_ignore_no_raw_html_no_dynamic_code", () => {
    const bad = {
      any: /:\s*any\b|\bas\s+any\b|<any>|\bany\[\]|Array<any>|Record<[^>]*\bany\b/,
      tsIgnore: /@ts-ignore|@ts-nocheck|@ts-expect-error/,
      html: /dangerouslySetInnerHTML|\.innerHTML\s*=|\binsertAdjacentHTML\b/,
      dyn: /\beval\s*\(|new\s+Function\s*\(/,
    };
    for (const [name, re] of Object.entries(bad)) {
      expect(ts.filter((p) => re.test(text(p))).map(rel), name).toEqual([]);
    }
  });

  it("WEB_4_static_no_model_id_and_no_support_js", () => {
    expect(sources.filter((p) => MODEL_ID.test(text(p))).map(rel)).toEqual([]);
    expect(sources.filter((p) => /support\.js/i.test(text(p))).map(rel)).toEqual([]);
  });

  it("WEB_4_static_css_selectors_sit_under_data_park", () => {
    for (const p of files.filter((f) => f.endsWith(".css"))) {
      const selectorLines = code(p)
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => /[,{]$/.test(l) && !l.startsWith("@"));
      for (const sel of selectorLines) expect(sel, rel(p)).toMatch(/^\[data-park\]/);
    }
  });
});

describe("WEB_4_static: imports", () => {
  const importsOf = (p: string): string[] =>
    [...code(p).matchAll(/(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] ?? "");

  it("WEB_4_static_imports_only_react_and_park_modules_never_screens_world_stage_or_other_pages", () => {
    const bad: string[] = [];
    for (const p of ts) {
      for (const spec of importsOf(p)) {
        if (!spec.startsWith(".")) {
          if (!/^react(\/|$)/.test(spec)) bad.push(`${rel(p)} imports ${spec}`);
          continue;
        }
        const target = resolve(dirname(p), spec);
        if (target === HOME || target.startsWith(`${HOME}\\`) || target.startsWith(`${HOME}/`))
          continue;
        if (target.startsWith(PAGES)) {
          bad.push(`${rel(p)} imports another page: ${spec}`);
          continue;
        }
        // The four connector-free task suggestions are config, not code (config/home_suggestions.json).
        if (target.replaceAll("\\", "/").endsWith("/config/home_suggestions.json")) continue;
        if (!target.startsWith(PARK)) bad.push(`${rel(p)} imports outside park/: ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
