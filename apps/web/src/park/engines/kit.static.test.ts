// WEB-1c static checks over apps/web/src/park/engines/kit.ts (plan sections 2, 5, 6; ADR-0003a; root CLAUDE.md
// hard rules). The same ideas as the WEB-1b engines.static.test.ts, written for the one new file:
// - kit.ts exists and exports createKit(h, deps) and ICON_NAMES, with the "ported from ... (user's prototype,
//   ADR-0003a)" header naming tilo-app.js;
// - no window.* or globalThis assignment, no window or document reference at all (the prototype's
//   `window.TiloWorld`, `window.TiloPark`, `window.TiloApp` and `ready()` globals are not ported), no
//   support.js, no eval or innerHTML, no model id, no clock, no Math.random, no timers, no network;
// - imports only the siblings ./world, ./park, ./types (so the WEB-1b sibling-import rule stays green);
// - no animation (WEB-3 restores motion): the honesty scan (FR-WLD-09) finds nothing and its allowlist is
//   not edited for this ticket;
// - no `any`, no ts directives (the kit.typecheck test compiles it too).
// Test files are excluded from the walk (they name these patterns on purpose).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../test-support/honestyScan";
import { ENGINES_DIR } from "../../../test-support/park/engineProto";

const KIT = join(ENGINES_DIR, "kit.ts");
const exists = (() => {
  try {
    readFileSync(KIT, "utf8");
    return true;
  } catch {
    return false;
  }
})();
const text = (): string => {
  if (!exists) throw new Error("apps/web/src/park/engines/kit.ts is missing: nothing to check");
  return readFileSync(KIT, "utf8");
};
/** Source with comments removed, so a comment that names a forbidden thing does not trip a check. */
const code = (): string =>
  text()
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
const lines = (): { line: number; text: string }[] =>
  code()
    .split(/\r?\n/)
    .map((t, i) => ({ line: i + 1, text: t.trim() }));

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID_STRICT = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_1c_static: kit.ts exists with the exported surface and header", () => {
  it("WEB_1c_static_kit_ts_exists_in_park_engines", () => {
    expect(exists, "apps/web/src/park/engines/kit.ts is missing").toBe(true);
  });

  it("WEB_1c_static_exports_createKit_taking_h_and_deps", () => {
    const src = text().replace(/\s+/g, " ");
    expect(src).toMatch(/export function createKit\(\s*h: H\b/);
    expect(src, "deps carries the plan source").toMatch(/\bplans\b/);
    expect(src, "and the optional browser calls, named env").toMatch(/\benv\b/);
  });

  it("WEB_1c_static_exports_ICON_NAMES", () => {
    expect(text()).toMatch(/export\s+const\s+ICON_NAMES\b/);
  });

  it("WEB_1c_static_names_its_source_in_the_header", () => {
    const head = text().slice(0, 600).toLowerCase();
    expect(head).toContain(
      "ported from design_handoff_tilo_web_app/design/tilo-app.js (user's prototype, adr-0003a)",
    );
  });

  it("WEB_1c_static_builds_the_two_engines_it_exposes", () => {
    const c = code();
    expect(c).toMatch(/createWorld\s*\(\s*h\s*\)/);
    expect(c).toMatch(/createPark\s*\(\s*h\s*,\s*createWorld\b/);
  });
});

describe("WEB_1c_static: no support.js, no window globals, no browser globals, no model ids", () => {
  it("WEB_1c_static_no_support_js_reference", () => {
    expect(text()).not.toMatch(/support\.js/i);
  });

  it("WEB_1c_static_no_window_global_is_assigned", () => {
    const hits = lines()
      .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text)))
      .map((l) => `kit.ts:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1c_static_the_window_scanner_catches_each_form", () => {
    for (const bad of [
      "window.TiloApp = { data, kit, ready };",
      "window.TiloWorld ||= f;",
      "window['TiloApp'] = f;",
      "globalThis.TiloApp = f;",
      "(window as unknown as Record<string, unknown>).TiloApp = f;",
      "Object.assign(window, { TiloApp });",
    ]) {
      expect(
        WINDOW_ASSIGN.some((re) => re.test(bad)),
        bad,
      ).toBe(true);
    }
    expect(WINDOW_ASSIGN.some((re) => re.test("if (window.innerWidth === 3) {}"))).toBe(false);
  });

  it("WEB_1c_static_no_window_document_or_other_browser_global_in_code", () => {
    const hits = lines()
      .filter((l) => /\b(?:window|document|navigator|localStorage|sessionStorage)\b/.test(l.text))
      .map((l) => `kit.ts:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1c_static_no_eval_no_Function_constructor_no_innerHTML", () => {
    expect(code()).not.toMatch(
      /\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(\s*["'`]|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write/,
    );
  });

  it("WEB_1c_static_no_model_id", () => {
    expect(MODEL_ID_STRICT.test(code())).toBe(false);
    expect(/nvidia\//i.test(code())).toBe(false);
  });

  it("WEB_1c_static_no_clock_no_Math_random_no_network_no_console", () => {
    const re =
      /\bMath\.random\b|\bDate\b|\bperformance\.now\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bconsole\./;
    const hits = lines()
      .filter((l) => re.test(l.text))
      .map((l) => `kit.ts:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });

  it("WEB_1c_static_no_module_level_state_the_cache_lives_inside_createKit", () => {
    // The prototype's `let K = null` singleton is replaced by instances: no top-level let or var, and no
    // top-level object or Map that could be a shared cache.
    const top = code()
      .split(/\r?\n/)
      .filter(
        (l) =>
          /^(?:let|var)\s/.test(l) ||
          /^const\s+\w+\s*(?::[^=]+)?=\s*(?:\{\s*\}|new\s+(?:Map|WeakMap|Set)\b|\[\s*\])/.test(l),
      );
    expect(top).toEqual([]);
  });
});

describe("WEB_1c_static: imports", () => {
  it("WEB_1c_static_imports_only_the_sibling_files_world_park_types", () => {
    // Siblings only, so the WEB-1b rule (engines.static.test.ts: every import in park/engines is a ./sibling)
    // stays green with kit.ts in the folder. The kit declares the small Dec / plan / world-slice types it
    // needs itself (or in ./types); the kit.typecheck probe checks the typed fixtures' types fit them.
    const bad: string[] = [];
    const c = code();
    for (const m of c.matchAll(/(?:from|import\s*\(|require\s*\()\s*["']([^"']+)["']/g)) {
      const spec = m[1] ?? "";
      if (!["./world", "./park", "./types"].includes(spec)) bad.push(`imports "${spec}"`);
    }
    if (/\bimport\s+["']/.test(c)) bad.push("a side-effect import");
    expect(bad, "no screens/, world/, stage/, ../api, react, pixi or node: imports").toEqual([]);
  });

  it("WEB_1c_static_uses_createWorld_and_createPark_from_the_siblings", () => {
    const c = code();
    expect(c).toMatch(/import\s*\{[^}]*\bcreatePark\b[^}]*\}\s*from\s*["']\.\/park["']/);
    expect(c).toMatch(/import\s*\{[^}]*\bcreateWorld\b[^}]*\}\s*from\s*["']\.\/world["']/);
  });
});

describe("WEB_1c_static: no animation in the kit (BQ-WEB-3, ADR-0003a 5; HR-1 to HR-3)", () => {
  it("WEB_1c_static_honesty_scan_finds_nothing_in_kit_ts", () => {
    expect(exists).toBe(true);
    const found = scanSource("src/park/engines/kit.ts", text());
    expect(found.map((v) => `${v.file}:${v.line} ${v.rule}: ${v.text}`)).toEqual([]);
  });

  it("WEB_1c_static_the_honesty_allowlist_is_untouched_by_this_ticket", () => {
    expect(ALLOWLIST.filter((a) => /park/.test(a.file))).toEqual([]);
  });

  it("WEB_1c_static_the_scan_is_not_vacuous_it_flags_each_form_the_prototype_used", () => {
    const flagged = (s: string) => scanSource("src/park/engines/kit.ts", s).length > 0;
    expect(flagged("const a = { animation: `mvXY 3s linear infinite` };")).toBe(true);
    expect(flagged("requestAnimationFrame(tick);")).toBe(true);
    expect(flagged("setInterval(f, 100);")).toBe(true);
    expect(flagged("const x = 1;")).toBe(false);
  });

  it("WEB_1c_static_no_animation_word_or_timer_in_kit_code_even_where_the_scan_would_not_look", () => {
    const re =
      /animation|keyframes|\bmvXY\b|\bwaddle\b|\bsprite2\b|\btiloDash\b|\btiloBob\b|\btiloGhost\b|\bsetTimeout\b|\bsetInterval\b|requestAnimationFrame|requestIdleCallback|\.animate\b|<animate|\btransition\b/i;
    const hits = lines()
      .filter((l) => re.test(l.text))
      .map((l) => `kit.ts:${l.line} ${l.text}`);
    expect(hits).toEqual([]);
  });
});
