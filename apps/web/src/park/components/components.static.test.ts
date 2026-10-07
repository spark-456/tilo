// WEB-2 static checks over src/park/components and src/park/dev (plan sections 2, 4, 6; ADR-0003a 5;
// root CLAUDE.md hard rules): no window globals, no `any` or ts-ignore, no support.js, no raw HTML, no
// timers (the 4.2 s toast hide and every other motion belong to WEB-3), imports only from react and park/,
// no model ids, the honesty scan finds nothing and its allowlist is unchanged, and /dev/components is
// registered in the dev build only without pulling park code into the landing bundle.
// Test files are excluded from the walk (they name these patterns on purpose).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, RULES, scanSource } from "../../../test-support/honestyScan";

// The Park city's ambient scenery (shell and engines) is decoration, not work: its animation entries are
// pinned by src/honesty/park-ambient.allowlist.test.ts. Every other entry stays pinned exactly here.
const AMBIENT = /^src\/park\/(shell|engines)\//;
import { COMPONENTS_DIR } from "../../../test-support/park/componentsCss";
import { PARK_DIR } from "../../../test-support/park/prototype";
import { parkTypeErrors } from "../../../test-support/park/typecheck";

const WEB = resolve(PARK_DIR, "..", "..");
const DEV_DIR = join(PARK_DIR, "dev");

function walk(dir: string): string[] {
  try {
    statSync(dir);
  } catch {
    return [];
  }
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.test\.tsx?$/.test(name) ? [] : [p];
  });
}

const files = [...walk(COMPONENTS_DIR), ...walk(DEV_DIR)];
const rel = (p: string) => relative(PARK_DIR, p).replaceAll("\\", "/");
const text = (p: string) => readFileSync(p, "utf8");
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const sources = files.filter((p) => /\.tsx?$/.test(p));
const codeFiles = files.filter((p) => /\.(tsx?|css)$/.test(p));

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
  /Reflect\.set\s*\(\s*(?:window|globalThis)\b/,
];
const ANY_TYPE = /(?::\s*|\bas\s+|<\s*|,\s*|\|\s*|&\s*)any\b(?![\w-])/;
const TS_DIRECTIVE = /@ts-(?:ignore|nocheck|expect-error)/;
const TIMERS =
  /\b(?:setTimeout|setInterval|setImmediate|clearTimeout|clearInterval|requestAnimationFrame|cancelAnimationFrame|requestIdleCallback)\b/;
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;
const MOTION_MARKER = /motion: restored in WEB-3 \(BQ-WEB-3\)/g;

describe("WEB_2_static: the scanned tree is not empty", () => {
  it.each(["components/index.ts", "components/park.components.css", "dev/Components.tsx"])(
    "WEB_2_static_has_%s",
    (f) => {
      expect(files.map(rel), "the builder's file is missing").toContain(f);
    },
  );

  it("WEB_2_static_there_is_one_source_file_per_component_or_more_not_one_blob", () => {
    const tsx = files.filter((p) => rel(p).startsWith("components/") && p.endsWith(".tsx"));
    expect(tsx.length).toBeGreaterThanOrEqual(8);
  });
});

describe("WEB_2_static: no window globals, any, ts-ignore, support.js, raw html, timers, model ids", () => {
  it("WEB_2_static_no_window_global_is_assigned", () => {
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

  it("WEB_2_static_no_any_and_no_ts_directives_in_sources", () => {
    const anys = sources.filter((p) => ANY_TYPE.test(code(p))).map(rel);
    expect(anys, "type it, do not use any").toEqual([]);
    const dirs = sources.filter((p) => TS_DIRECTIVE.test(text(p))).map(rel);
    expect(dirs).toEqual([]);
  });

  it("WEB_2_static_the_any_and_directive_scanners_catch_each_form", () => {
    for (const bad of ["const a: any = 1;", "x as any", "Array<any>", "f(a, any)", "T | any"])
      expect(ANY_TYPE.test(bad), bad).toBe(true);
    for (const fine of ["const company = 1;", "// any thing", "anyone()", "many: number"])
      expect(ANY_TYPE.test(fine), fine).toBe(false);
    expect(TS_DIRECTIVE.test("// @ts-ignore")).toBe(true);
    expect(TIMERS.test("setTimeout(f, 1)")).toBe(true);
    expect(TIMERS.test("requestAnimationFrame(f)")).toBe(true);
    expect(TIMERS.test("const timeout = 1")).toBe(false);
  });

  it("WEB_2_static_no_support_js_reference", () => {
    expect(files.filter((p) => /support\.js/i.test(text(p))).map(rel)).toEqual([]);
  });

  it("WEB_2_static_no_raw_html_or_dynamic_code", () => {
    const hits = codeFiles
      .filter((p) =>
        /\beval\s*\(|new\s+Function\s*\(|dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML/.test(
          code(p),
        ),
      )
      .map(rel);
    expect(hits).toEqual([]);
  });

  it("WEB_2_static_no_timers_or_frame_loops_in_components_or_the_dev_page", () => {
    const hits = sources.filter((p) => TIMERS.test(code(p))).map(rel);
    expect(hits, "the toast's 4.2 s auto-hide is the shell store's (WEB-3)").toEqual([]);
  });

  it("WEB_2_static_no_model_id", () => {
    expect(codeFiles.filter((p) => MODEL_ID.test(text(p))).map(rel)).toEqual([]);
  });

  it("WEB_2_static_no_network_or_clock_or_random", () => {
    const banned =
      /\bMath\.random\b|\bDate\.now\b|\bnew\s+Date\s*\(|\bperformance\.now\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b/;
    expect(sources.filter((p) => banned.test(code(p))).map(rel)).toEqual([]);
  });
});

describe("WEB_2_static: imports come from react and park/ only", () => {
  it("WEB_2_static_imports_are_react_or_inside_park", () => {
    const bad: string[] = [];
    for (const p of sources) {
      const body = code(p);
      const specs = [
        ...body.matchAll(/\bfrom\s*["']([^"']+)["']/g),
        ...body.matchAll(/(?:^|\n)\s*import\s*["']([^"']+)["']/g),
        ...body.matchAll(/\bimport\s*\(\s*["']([^"']+)["']\s*\)/g),
      ].map((m) => m[1] as string);
      for (const s of specs) {
        if (s === "react" || s === "react/jsx-runtime") continue;
        if (s.startsWith(".")) {
          const target = resolve(dirname(p), s);
          if (
            target === PARK_DIR ||
            target.startsWith(`${PARK_DIR}\\`) ||
            target.startsWith(`${PARK_DIR}/`)
          )
            continue;
        }
        bad.push(`${rel(p)} imports ${s}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("WEB_2_static_nothing_is_imported_from_screens_world_stage_or_the_old_design_system", () => {
    const bad = sources.filter((p) =>
      /from\s*["'][^"']*\/(?:screens|world|stage|needs-you|people|assistant|design|display)\//.test(
        code(p),
      ),
    );
    expect(bad.map(rel)).toEqual([]);
  });
});

describe("WEB_2_static: honesty (FR-WLD-09) and motion (BQ-WEB-3)", () => {
  it("WEB_2_static_honesty_scan_finds_nothing_in_components_and_dev", () => {
    expect(codeFiles.length).toBeGreaterThanOrEqual(5);
    const hits = codeFiles.flatMap((p) => scanSource(`src/park/${rel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_2_static_the_honesty_allowlist_and_rules_are_unchanged", () => {
    expect(
      ALLOWLIST.filter((e) => !AMBIENT.test(e.file)).map((e) => `${e.file}|${e.rule}`),
    ).toEqual(["src/world/runWorld.ts|raf", "src/stage/Stage.tsx|raf"]);
    expect(RULES.map((r) => r.id)).toEqual([
      "raf",
      "interval",
      "waapi",
      "waapi-bracket",
      "pixi-ticker",
      "tween-library",
      "inline-motion-style",
      "style-assign-motion",
      "smooth-scroll-js",
      "smil",
      "view-transition",
      "css-keyframes",
      "css-animation",
      "css-transition",
      "css-smooth-scroll",
    ]);
  });

  it("WEB_2_static_no_inline_transition_or_animation_style_in_sources", () => {
    const hits = sources
      .filter((p) => /\b(?:transition|animation)(?:[A-Z]\w*)?\s*[:=]/.test(code(p)))
      .map(rel);
    expect(hits).toEqual([]);
  });

  it("WEB_2_static_each_place_where_the_README_has_motion_is_marked_for_WEB_3", () => {
    const all = codeFiles.map((p) => text(p)).join("\n");
    const marks = all.match(MOTION_MARKER) ?? [];
    // hover brightness is a state; the sliding thumb and the switch knob are the motion sites (README
    // "Core components"). Two marks at least, in the source or the stylesheet.
    expect(marks.length).toBeGreaterThanOrEqual(2);
  });
});

describe("WEB_2_static: /dev/components is a dev-build route", () => {
  const routes = readFileSync(join(WEB, "src", "screens", "routes.tsx"), "utf8");

  it("WEB_2_static_route_row_sits_inside_the_import_meta_env_DEV_branch_of_EXTRA", () => {
    const m = /import\.meta\.env\.DEV\s*\?\s*\[([\s\S]*?)\]\s*:\s*\[\]/.exec(routes);
    expect(m, "the EXTRA table keeps its `import.meta.env.DEV ? [...] : []` branch").not.toBeNull();
    const dev = m?.[1] ?? "";
    expect(dev).toMatch(/id:\s*"dev-components"/);
    expect(dev).toMatch(/\\\/dev\\\/components/);
    expect(dev, "the existing dev rows stay").toContain('id: "screens"');
    expect(dev).not.toContain('id: "more"');
    expect(routes).toMatch(/id:\s*"more"/);
  });

  it("WEB_2_static_the_page_is_lazy_loaded_so_park_code_stays_off_the_landing_bundle", () => {
    expect(routes).not.toMatch(/^import\s[^;]*from\s*["']\.\.\/park\//m);
    expect(routes).toMatch(/import\(\s*["']\.\.\/park\/dev\/Components["']\s*\)/);
  });

  it("WEB_2_static_the_dev_page_is_a_named_export_Components", () => {
    const src = text(join(DEV_DIR, "Components.tsx"));
    expect(src).toMatch(/export\s+(?:function|const)\s+Components\b/);
    expect(src).not.toMatch(/export\s+default/);
  });
});

describe("WEB_2_static: apps/web/CLAUDE.md is untouched", () => {
  it("WEB_2_static_claude_md_stays_at_40_lines_and_does_not_name_the_new_files", () => {
    const md = readFileSync(join(WEB, "CLAUDE.md"), "utf8");
    expect(md.replace(/\n$/, "").split("\n").length).toBeLessThanOrEqual(40);
    expect(md).not.toMatch(/dev\/components|park\.components|park\/components/);
  });
});

describe("WEB_2_typecheck: the new files compile with the repo's strict options", () => {
  it(
    "WEB_2_typecheck_components_dev_and_their_tests_have_no_type_errors",
    { timeout: 180_000 },
    () => {
      const mine = parkTypeErrors().filter((e) =>
        /^(?:src\/park\/components\/|src\/park\/dev\/|test-support\/park\/components)/.test(e),
      );
      expect(mine).toEqual([]);
    },
  );
});
