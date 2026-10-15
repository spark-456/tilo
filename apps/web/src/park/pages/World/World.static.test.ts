// WEB-6 static checks over apps/web/src/park/pages/World (plan sections 6 and 10; root CLAUDE.md hard rules):
// - the page folder holds WorldPage.tsx (NAMED export WorldPage, no default export) and World.css; the registry
//   has one line for it;
// - data only through useParkApi (no fixture or live Api import, no fetch), navigation only through app.go
//   (no address-bar reads except the one `location.href` the Share button copies, as the reference does),
//   approvals only through app.decide, no timer of its own (a delay would go through useSchedule);
// - no transition / animation / keyframes (BQ-WEB-3: the reference's `transition: width .5s` on the bars and
//   the `tiloSpin` ring return with the WEB-3 motion restore; until then the bars jump and the ring is still),
//   no Math.random, no clock, no `any`, no @ts-ignore, no window assignment, no raw HTML, no model id,
//   no support.js; imports only react, park/components, park/engines, park/api and park/app;
// - nothing from screens/, world/, stage/ or another page; the honesty scan finds nothing; ALLOWLIST unchanged;
// - "No scenario-specific code": the scenario's world ids, names and amounts are data.
// Test files are excluded from the walk (they name these patterns on purpose).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../../test-support/honestyScan";

// The Park city's ambient scenery (shell and engines) is decoration, not work: its animation entries are
// pinned by src/honesty/park-ambient.allowlist.test.ts. Every other entry stays pinned exactly here.
const AMBIENT = /^src\/(park\/(shell|engines)|landing)\//; // LANDING-2: the landing's own chrome motion

const WORLD = __dirname;
const PAGES = resolve(WORLD, "..");
const PARK = resolve(PAGES, "..");

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
const rel = (p: string) => relative(WORLD, p).replaceAll("\\", "/");

const files = walk(WORLD);
const sources = files.filter((p) => /\.(tsx?|css)$/.test(p));
const ts = files.filter((p) => /\.tsx?$/.test(p));

// Every check below walks the page's own files: with no page there is nothing to pass vacuously.
beforeEach(() => {
  expect(ts.map(rel), "src/park/pages/World/WorldPage.tsx is missing").toContain("WorldPage.tsx");
});

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_6_static: the page folder", () => {
  it("WEB_6_static_the_folder_holds_WorldPage_tsx_and_World_css", () => {
    const names = files.map(rel);
    expect(names).toContain("WorldPage.tsx");
    expect(names).toContain("World.css");
  });

  it("WEB_6_static_WorldPage_is_a_named_export_taking_app_and_has_no_default_export", () => {
    const src = code(join(WORLD, "WorldPage.tsx"));
    expect(src).toMatch(/export\s+(?:function|const)\s+WorldPage\b/);
    expect(src).not.toMatch(/export\s+default\b/);
    expect(src).toMatch(/import\s+["']\.\/World\.css["']/);
  });

  it("WEB_6_static_pages_ts_gains_one_line_for_world_and_keeps_the_other_eight", () => {
    const src = readFileSync(join(PARK, "app", "pages.ts"), "utf8");
    const lines = src.split(/\r?\n/).filter((l) => /^\s*world\s*:/.test(l));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatch(/pages\/World\/WorldPage/);
    expect(lines[0]).not.toMatch(/Placeholder/);
    for (const id of [
      "home",
      "worlds",
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

  it("WEB_6_static_the_page_has_no_main_landmark_of_its_own_and_draws_one_h1", () => {
    const all = ts.map((p) => code(p)).join("\n");
    expect(all).not.toMatch(/<main\b|role=["']main["']/);
    expect((all.match(/<h1\b/g) ?? []).length).toBeGreaterThanOrEqual(1);
  });
});

describe("WEB_6_static: honesty (HR-1..HR-7; the scan and its allowlist are untouched)", () => {
  it("WEB_6_static_ALLOWLIST_is_unchanged", () => {
    expect(
      ALLOWLIST.filter((e) => !AMBIENT.test(e.file)).map((e) => `${e.file}:${e.rule}`),
    ).toEqual(["src/world/runWorld.ts:raf", "src/stage/Stage.tsx:raf"]);
  });

  it("WEB_6_static_the_honesty_scan_finds_nothing_in_the_page", () => {
    expect(sources.length).toBeGreaterThanOrEqual(2);
    const hits = sources.flatMap((p) => scanSource(`src/park/pages/World/${rel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_6_static_no_transition_animation_keyframes_raf_interval_timeout_random_or_clock", () => {
    const banned =
      /\btransition\b|\banimation\b|@keyframes|tiloSpin|requestAnimationFrame|cancelAnimationFrame|setInterval|setTimeout|clearTimeout|\.animate\s*\(|\bMath\.random\b|\bDate\.now\b|\bnew\s+Date\b|\bperformance\.now\b/;
    expect(sources.filter((p) => banned.test(code(p))).map(rel)).toEqual([]);
  });

  it("WEB_6_static_World_css_marks_where_the_design_moves_for_the_WEB_3_restore", () => {
    // The progress bars (`transition: width .5s`) and the Village spinner (`tiloSpin .7s`) are designed motion.
    const css = text(join(WORLD, "World.css"));
    expect(css).toMatch(/motion: restored in WEB-3 \(BQ-WEB-3\)/);
  });
});

describe("WEB_6_static: data and navigation seams", () => {
  it("WEB_6_static_data_only_through_useParkApi", () => {
    expect(code(join(WORLD, "WorldPage.tsx"))).toMatch(/\buseParkApi\b/);
    for (const p of ts) {
      expect(code(p), rel(p)).not.toMatch(
        /api\/fixtures|fixtureApi|createFixtureApi|liveApi|createLiveApi|parkApi\b|\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource/,
      );
    }
  });

  it("WEB_6_static_navigation_through_app_go_and_approvals_through_app_decide", () => {
    const all = ts.map((p) => code(p)).join("\n");
    expect(all).toMatch(/\bapp\.go\(|\bgo\(/);
    expect(all).toMatch(/\bapp\.decide\(|\bdecide\(/);
  });

  it("WEB_6_static_no_address_bar_reads_except_the_one_location_href_of_Share", () => {
    const hits = ts.filter((p) =>
      /\bwindow\s*\.\s*location\b|\bdocument\s*\.\s*location\b|\bwindow\s*\.\s*history\b|\bhistory\s*\.\s*(?:push|replace)State\b|\blocation\s*\.\s*(?:pathname|search|hash|assign|replace|reload|origin)\b|\bnavigatePark\b|\bparkPath\b|\bnavigateFlow\b|\buseNavigate\b|\bwindow\s*\.\s*open\b/.test(
        code(p),
      ),
    );
    expect(hits.map(rel)).toEqual([]);
    const href = ts.flatMap((p) => code(p).match(/\blocation\s*\.\s*href\b/g) ?? []);
    expect(href.length, "the reference reads location.href once, in Share").toBeLessThanOrEqual(1);
  });

  it("WEB_6_static_the_clipboard_write_is_guarded", () => {
    const src = ts.map((p) => code(p)).join("\n");
    const at = src.search(/clipboard/);
    expect(at, "Share writes to the clipboard").toBeGreaterThan(-1);
    const around = src.slice(Math.max(0, at - 400), at + 400);
    expect(around, "try/catch or .catch around navigator.clipboard").toMatch(/\btry\b|\.catch\(/);
  });
});

describe("WEB_6_static: no scenario-specific code", () => {
  const FORBIDDEN: [string, RegExp][] = [
    ["world id k1", /\bk1\b/i],
    [
      "a fixture world id",
      /["'`](?:hires|audit|northline|invoice|inbox|pricing|calls|venues|comp|reply)["'`]/,
    ],
    ["supplier name", /Laptop Depot/i],
    ["product name", /scooter/i],
    ["company name", /Meridian|Northwind|Northline/i],
    ["person", /Alex Morgan|Priya Shah|Jin Park|Tom Reyes|alex@northwind/i],
    ["amount", /3,?420|2,?500/],
    ["goods", /battery|suppliers?\b/i],
    ["agent role", /Builder agent/i],
    ["button label", /Send brief|Approve £/i],
    ["level line", /Level \d of \d|Prototypes and suppliers/i],
    ["decision key", /["'`](?:depot|mail)["'`]/],
  ];
  it("WEB_6_static_the_page_holds_no_scenario_literal", () => {
    expect(sources.length).toBeGreaterThanOrEqual(2);
    for (const p of sources) {
      for (const [what, re] of FORBIDDEN) expect(code(p), `${rel(p)}: ${what}`).not.toMatch(re);
    }
  });
});

describe("WEB_6_static: code hygiene", () => {
  it("WEB_6_static_no_window_global_is_assigned", () => {
    const hits = sources.flatMap((p) =>
      code(p)
        .split(/\r?\n/)
        .map((line, i) => ({ file: rel(p), line: i + 1, text: line.trim() }))
        .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text)))
        .map((l) => `${l.file}:${l.line} ${l.text}`),
    );
    expect(hits).toEqual([]);
  });

  it("WEB_6_static_no_any_no_ts_ignore_no_raw_html_no_dynamic_code", () => {
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

  it("WEB_6_static_no_model_id_and_no_support_js", () => {
    expect(sources.filter((p) => MODEL_ID.test(text(p))).map(rel)).toEqual([]);
    expect(sources.filter((p) => /support\.js/i.test(text(p))).map(rel)).toEqual([]);
  });

  it("WEB_6_static_colours_in_code_are_tokens_except_the_ones_the_README_hard_codes", () => {
    for (const p of sources) {
      const hex = [...code(p).matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toUpperCase());
      for (const h of hex) {
        expect(["#F0A500", "#1F1D2B", "#FFFFFF", "#5A3FE0"], `${rel(p)}: ${h}`).toContain(h);
      }
    }
  });

  it("WEB_6_static_css_selectors_sit_under_data_park", () => {
    for (const p of files.filter((f) => f.endsWith(".css"))) {
      const selectorLines = code(p)
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => /[,{]$/.test(l) && !l.startsWith("@"));
      for (const sel of selectorLines) expect(sel, rel(p)).toMatch(/^\[data-park\]/);
    }
  });
});

describe("WEB_6_static: imports", () => {
  const importsOf = (p: string): string[] =>
    [...code(p).matchAll(/(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] ?? "");

  it("WEB_6_static_imports_only_react_and_park_modules_never_screens_world_stage_or_other_pages", () => {
    const bad: string[] = [];
    for (const p of ts) {
      for (const spec of importsOf(p)) {
        if (!spec.startsWith(".")) {
          if (!/^react(\/|$)/.test(spec)) bad.push(`${rel(p)} imports ${spec}`);
          continue;
        }
        const target = resolve(dirname(p), spec);
        if (target === WORLD || target.startsWith(`${WORLD}\\`) || target.startsWith(`${WORLD}/`))
          continue;
        if (target.startsWith(PAGES)) {
          bad.push(`${rel(p)} imports another page: ${spec}`);
          continue;
        }
        if (!target.startsWith(PARK)) bad.push(`${rel(p)} imports outside park/: ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
