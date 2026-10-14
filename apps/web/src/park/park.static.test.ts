// WEB-1a static checks over apps/web/src/park (plan sections 2, 5, 6; root CLAUDE.md hard rules):
// - support.js (Claude Design's runtime) is never ported or referenced;
// - no `window.*` / globalThis globals are assigned (the prototype's window.TiloApp is not carried over);
// - no model id (PL-01); no dynamic code (no eval, no innerHTML);
// - the api layer is deterministic (no clock, no random) and makes no network call (nothing is live yet);
// - park imports nothing from screens/, world/ or stage/ (only the shared src/api client seam is allowed);
// - the honesty scan (FR-WLD-09) finds nothing in park/tokens and park/api.
// Test files are excluded from the walk (they name these patterns on purpose).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { scanSource } from "../../test-support/honestyScan";

const PARK = __dirname;
const SRC = resolve(PARK, "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.test\.tsx?$/.test(name) ? [] : [p];
  });
}

const RUN_ENGINE = [
  "world/runLog",
  "world/runSummary",
  "world/worldContext",
  "world/autopilot",
  // Shared seams that are not part of any old screen: the router and the display-density store.
  "router",
  "display/density",
];

const files = walk(PARK);
const rel = (p: string) => relative(PARK, p).replaceAll("\\", "/");
const text = (p: string) => readFileSync(p, "utf8");
/** Source with comments removed, so a comment that names a forbidden thing does not trip a check. */
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const codeFiles = files.filter((p) => /\.(tsx?|css)$/.test(p));

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_1a_static: the scanned tree is not empty", () => {
  it.each([
    "api/index.ts",
    "api/types.ts",
    "api/fixtureApi.ts",
    "api/liveApi.ts",
    "api/select.ts",
    "api/fixtures/index.ts",
    "tokens/park.css",
    "tokens/ramp.ts",
    "tokens/fonts.ts",
  ])("WEB_1a_static_park_has_%s", (f) => {
    expect(files.map(rel), "the builder's file is missing").toContain(f);
  });
});

describe("WEB_1a_static: no support.js, no window globals, no model ids", () => {
  it("WEB_1a_static_no_support_js_reference_anywhere_in_park", () => {
    const hits = files.filter((p) => /support\.js/i.test(text(p))).map(rel);
    expect(hits, "support.js is Claude Design's runtime and is never ported or named").toEqual([]);
  });

  it("WEB_1a_static_no_window_global_is_assigned", () => {
    const hits = codeFiles
      .flatMap((p) =>
        code(p)
          .split(/\r?\n/)
          .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
          .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text))),
      )
      .map((l) => `${l.file}:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1a_static_the_window_scanner_catches_each_form", () => {
    for (const bad of [
      "window.TiloApp = { data };",
      "window.TiloApp ||= x;",
      "window['TiloApp'] = x;",
      "globalThis.TiloApp = x;",
      "(window as any).TiloApp = x;",
      "Object.assign(window, { TiloApp });",
      "Object.defineProperty(globalThis, 'x', {});",
    ]) {
      expect(
        WINDOW_ASSIGN.some((re) => re.test(bad)),
        bad,
      ).toBe(true);
    }
    for (const fine of [
      "const w = window.innerWidth;",
      "window.addEventListener('resize', f);",
      "if (window.matchMedia('(min-width: 1100px)').matches) go();",
      "const same = window.location.pathname === '/park/home';",
    ]) {
      expect(
        WINDOW_ASSIGN.some((re) => re.test(fine)),
        fine,
      ).toBe(false);
    }
  });

  it("WEB_1a_static_no_model_id_in_park", () => {
    const hits = codeFiles.filter((p) => MODEL_ID.test(text(p))).map(rel);
    expect(hits, "PL-01: models are configuration, never named here").toEqual([]);
    // Assembled at runtime so this file holds no model id for the repo-wide PL-01 lint.
    expect(MODEL_ID.test(["gemini", "3.8-flash"].join("-"))).toBe(true);
    expect(MODEL_ID.test("the Claude-ish tone")).toBe(true);
    expect(MODEL_ID.test("the park clock")).toBe(false);
  });

  it("WEB_1a_static_no_dynamic_code_or_raw_html", () => {
    const hits = codeFiles
      .filter((p) =>
        /\beval\s*\(|new\s+Function\s*\(|dangerouslySetInnerHTML|\.innerHTML\s*=/.test(code(p)),
      )
      .map(rel);
    expect(hits).toEqual([]);
  });
});

describe("WEB_1a_static: the api layer is deterministic and offline", () => {
  const apiFiles = codeFiles.filter((p) => rel(p).startsWith("api/"));

  it("WEB_1a_static_api_has_no_clock_no_random_no_network", () => {
    const banned =
      /\bMath\.random\b|\bDate\.now\b|\bnew\s+Date\s*\(|\bperformance\.now\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|\bsendBeacon\b/;
    // FR-SPD-07 parses only a recorded timestamp. No zero-argument constructor
    // or other Date construction is exempt; fixed-clock behavior is tested below.
    const hits = apiFiles
      .filter((p) => {
        const source =
          rel(p) === "api/live/ledgerFromCosts.ts"
            ? code(p).replace(/\bnew\s+Date\s*\(\s*e\.ts\s*\)/g, "recordedTimestamp")
            : code(p);
        return banned.test(source);
      })
      .map(rel);
    expect(hits, "fixtures are fixed at September 2026 and nothing is live yet").toEqual([]);
    expect(apiFiles.length).toBeGreaterThan(0);
  });
});

describe("WEB_1a_static: park stays beside the old app", () => {
  it("WEB_1a_static_park_imports_nothing_from_screens_world_or_stage", () => {
    const bad: string[] = [];
    for (const p of codeFiles.filter((f) => /\.tsx?$/.test(f))) {
      for (const m of code(p).matchAll(/\b(?:from|import)\s*\(?\s*["'](\.[^"']*)["']/g)) {
        const target = resolve(dirname(p), m[1] ?? "");
        if (target.startsWith(PARK)) continue;
        const inSrc = relative(SRC, target).replaceAll("\\", "/");
        // Only the shared API client seam (src/api) may be reused from outside park.
        // SEC-16: and the one shared lifetime-cap dialog (src/components, like ReplayBanner: neither tree imports the other).
        const shared = inSrc === "components/LifetimeCapDialog";
        // The run-admin sections read the live run through four engine modules the stage shares: the one named
        // exception to "nothing from world/" (the old app is gone; nothing else may be added here).
        const engine = RUN_ENGINE.includes(inSrc);
        if (!(inSrc === "api" || inSrc.startsWith("api/") || shared || engine))
          bad.push(`${rel(p)} imports ${m[1]}`);
      }
    }
    expect(bad).toEqual([]);
  });
});

describe("WEB_1a_static: park tokens and api pass the honesty scan (FR-WLD-09)", () => {
  it("WEB_1a_static_honesty_scan_finds_nothing_in_tokens_and_api", () => {
    const scanned = codeFiles.filter((p) => /^(tokens|api)\//.test(rel(p)));
    expect(scanned.length).toBeGreaterThanOrEqual(5);
    const hits = scanned.flatMap((p) => scanSource(`src/park/${rel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });
});
