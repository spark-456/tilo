// WEB-1b static checks over apps/web/src/park/engines (plan sections 2, 5, 6; ADR-0003a; root CLAUDE.md hard rules):
// - the three files exist (types.ts, world.ts, park.ts), with the exported surface the parity tests rely on;
// - each port carries the "ported from ... (user's prototype, ADR-0003a)" header;
// - no `window.*` / globalThis assignment, no window or document reference at all (browser calls go
//   through the injectable env), no support.js, no eval or innerHTML, no model id;
// - no clock and no Math.random (the prototype's seeded rng stays);
// - imports only from within park/engines;
// - WEB-1b adds no animation: the honesty scan (FR-WLD-09) finds nothing in the engine files, and its
//   allowlist is not edited for them.
// Test files are excluded from the walk (they name these patterns on purpose).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../test-support/honestyScan";
import { ENGINES_DIR } from "../../../test-support/park/engineProto";

function walk(dir: string): string[] {
  try {
    return readdirSync(dir).flatMap((name) => {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) return walk(p);
      return /\.test\.tsx?$/.test(name) ? [] : [p];
    });
  } catch {
    return [];
  }
}

const files = walk(ENGINES_DIR);
const rel = (p: string) => relative(ENGINES_DIR, p).replaceAll("\\", "/");
const text = (p: string) => readFileSync(p, "utf8");
const byName = (n: string) => files.find((p) => rel(p) === n);
/** Source with comments removed, so a comment that names a forbidden thing does not trip a check. */
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
const codeFiles = files.filter((p) => /\.(tsx?|css)$/.test(p));

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID_STRICT = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

// Every check below is vacuous on an empty tree, so each one first needs the three engine files.
beforeEach(() => {
  expect(codeFiles.length, "the engine files are missing: nothing to check").toBeGreaterThanOrEqual(
    3,
  );
});

describe("WEB_1b_static: the scanned tree is not empty", () => {
  it.each(["types.ts", "world.ts", "park.ts"])("WEB_1b_static_engines_has_%s", (f) => {
    expect(files.map(rel), "the builder's file is missing").toContain(f);
  });
});

describe("WEB_1b_static: exported surface and header", () => {
  it("WEB_1b_static_world_ts_exports_createWorld_and_names_its_source", () => {
    const f = byName("world.ts");
    expect(f, "world.ts").toBeDefined();
    const src = text(f as string);
    expect(src).toMatch(/export\s+function\s+createWorld\s*\(\s*h\s*:\s*H\b/);
    const head = src.slice(0, 600).toLowerCase();
    expect(head, "header comment").toContain(
      "ported from design_handoff_tilo_web_app/design/tilo-world.js (user's prototype, adr-0003a)",
    );
  });

  it("WEB_1b_static_park_ts_exports_createPark_with_an_env_and_names_its_source", () => {
    const f = byName("park.ts");
    expect(f, "park.ts").toBeDefined();
    const src = text(f as string);
    expect(src).toMatch(/export\s+function\s+createPark\s*\(/);
    expect(src, "the env argument is named env").toMatch(/\benv\b/);
    const head = src.slice(0, 600).toLowerCase();
    expect(head, "header comment").toContain(
      "ported from design_handoff_tilo_web_app/design/tilo-park.js (user's prototype, adr-0003a)",
    );
  });

  it("WEB_1b_static_types_ts_exports_H_and_ParkEnv", () => {
    const f = byName("types.ts");
    expect(f, "types.ts").toBeDefined();
    const src = text(f as string).replace(/\s+/g, " ");
    expect(src).toMatch(
      /export type H = \( ?tag: string, props: Record<string, unknown> \| null, \.\.\.children: unknown\[],? ?\) => unknown/,
    );
    expect(
      files.some((p) => /export\s+(?:type|interface)\s+ParkEnv\b/.test(text(p))),
      "ParkEnv (the injectable browser calls) is exported",
    ).toBe(true);
  });
});

describe("WEB_1b_static: no support.js, no window globals, no browser globals, no model ids", () => {
  it("WEB_1b_static_no_support_js_reference_anywhere", () => {
    const hits = files.filter((p) => /support\.js/i.test(text(p))).map(rel);
    expect(hits, "support.js is Claude Design's runtime and is never ported or named").toEqual([]);
  });

  it("WEB_1b_static_no_window_global_is_assigned", () => {
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

  it("WEB_1b_static_the_window_scanner_catches_each_form", () => {
    for (const bad of [
      "window.TiloWorld = f;",
      "window.TiloPark ||= f;",
      "window['TiloWorld'] = f;",
      "globalThis.TiloWorld = f;",
      "(window as any).TiloWorld = f;",
      "Object.assign(window, { TiloWorld });",
    ]) {
      expect(
        WINDOW_ASSIGN.some((re) => re.test(bad)),
        bad,
      ).toBe(true);
    }
    expect(WINDOW_ASSIGN.some((re) => re.test("if (window.innerWidth === 3) {}"))).toBe(false);
  });

  it("WEB_1b_static_no_window_or_document_reference_in_code_the_env_argument_carries_the_browser_calls", () => {
    const hits = codeFiles
      .flatMap((p) =>
        code(p)
          .split(/\r?\n/)
          .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
          .filter((l) =>
            /\b(?:window|document|navigator|localStorage|sessionStorage)\b/.test(l.text),
          ),
      )
      .map((l) => `${l.file}:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1b_static_no_eval_no_Function_constructor_no_innerHTML", () => {
    const re =
      /\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(\s*["'`]|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write/;
    const hits = codeFiles.filter((p) => re.test(code(p))).map(rel);
    expect(hits).toEqual([]);
  });

  it("WEB_1b_static_no_model_id", () => {
    const hits = codeFiles
      .filter((p) => MODEL_ID_STRICT.test(code(p)) || /nvidia\//i.test(code(p)))
      .map(rel);
    expect(hits).toEqual([]);
  });

  it("WEB_1b_static_no_clock_no_Math_random_no_network_no_console", () => {
    const re =
      /\bMath\.random\b|\bDate\b|\bperformance\.now\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bconsole\./;
    const hits = codeFiles
      .flatMap((p) =>
        code(p)
          .split(/\r?\n/)
          .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
          .filter((l) => re.test(l.text)),
      )
      .map((l) => `${l.file}:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1b_static_the_seeded_rng_is_kept_in_both_engines", () => {
    for (const n of ["world.ts", "park.ts"]) {
      const f = byName(n);
      expect(f, n).toBeDefined();
      // 0x6D2B79F5 is the mulberry32 constant of the prototype's rng; it stays, so scenes repeat.
      expect(code(f as string), n).toMatch(/0x6d2b_?79f5|1831565813/i);
    }
  });
});

describe("WEB_1b_static: imports stay inside park/engines", () => {
  it("WEB_1b_static_every_import_is_a_sibling_file_of_engines", () => {
    const bad: string[] = [];
    for (const p of codeFiles) {
      for (const m of code(p).matchAll(/(?:from|import\s*\(|require\s*\()\s*["']([^"']+)["']/g)) {
        const spec = m[1] ?? "";
        if (!/^\.\/[\w.-]+$/.test(spec)) bad.push(`${rel(p)} imports "${spec}"`);
      }
      if (/\bimport\s+["']/.test(code(p))) bad.push(`${rel(p)} has a side-effect import`);
    }
    expect(bad, "no screens/, world/, stage/, react, pixi or node: imports").toEqual([]);
  });
});

describe("WEB_1b_static: no animation in the engines (BQ-WEB-3, ADR-0003a 5; HR-1 to HR-3)", () => {
  it("WEB_1b_static_honesty_scan_finds_nothing_in_the_engine_files", () => {
    expect(files.length).toBeGreaterThanOrEqual(3);
    const found = codeFiles.flatMap((p) => scanSource(`src/park/engines/${rel(p)}`, text(p)));
    expect(found.map((v) => `${v.file}:${v.line} ${v.rule}: ${v.text}`)).toEqual([]);
  });

  it("WEB_1b_static_the_honesty_allowlist_is_untouched_by_this_ticket", () => {
    expect(ALLOWLIST.filter((a) => /park/.test(a.file))).toEqual([]);
  });

  it("WEB_1b_static_the_scan_is_not_vacuous_it_flags_each_form_the_prototype_used", () => {
    const flagged = (s: string) => scanSource("src/park/engines/x.ts", s).length > 0;
    expect(flagged("const a = { animation: `mvXY 3s linear infinite` };")).toBe(true);
    expect(flagged("requestAnimationFrame(tick);")).toBe(true);
    expect(flagged("setInterval(f, 100);")).toBe(true);
    expect(flagged("const css = '@keyframes mvXY{}';")).toBe(true);
    expect(flagged("const x = 1;")).toBe(false);
  });

  it("WEB_1b_static_no_animation_word_or_timer_in_engine_code_even_where_the_scan_would_not_look", () => {
    // Belt and braces for the scan's blind spots (quoted keys, computed names, timers): the prototype's
    // keyframe names, a timer or a Web Animations call may not appear anywhere in code.
    const re =
      /animation|keyframes|\bmvXY\b|\bwaddle\b|\bsprite2\b|\btiloDash\b|\btiloBob\b|\btiloGhost\b|\bsetTimeout\b|\bsetInterval\b|requestAnimationFrame|requestIdleCallback|\.animate\b|<animate|\btransition\b/i;
    const hits = codeFiles
      .flatMap((p) =>
        code(p)
          .split(/\r?\n/)
          .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
          .filter((l) => re.test(l.text)),
      )
      .map((l) => `${l.file}:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });
});
