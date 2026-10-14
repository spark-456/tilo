// WEB-5 static rules for pages/Worlds/ (plan section 10 helper contract; park/CLAUDE.md local rules; honesty
// rules HR-1..HR-7): no imports from screens/ world/ stage/, no window globals or address-bar reads, no timers
// or motion, strict TypeScript, scoped and prefixed CSS, and exactly one new line in park/app/pages.ts.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { scanSource } from "../../../../test-support/honestyScan";
import { parseRules } from "../../../../test-support/park/componentsCss";
import { stripComments } from "../../../../test-support/park/css";

const DIR = __dirname;
const files = existsSync(DIR) ? readdirSync(DIR).filter((f) => !/\.test\.tsx?$/.test(f)) : [];
const read = (f: string) => readFileSync(join(DIR, f), "utf8");
const code = (f: string) => stripComments(read(f)).replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const sources = files.filter((f) => /\.(tsx?|css)$/.test(f));
const tsFiles = files.filter((f) => /\.tsx?$/.test(f));
const cssFiles = files.filter((f) => f.endsWith(".css"));
/** The scans below are only meaningful once the page exists; an empty folder must not pass them. */
const built = () => expect(tsFiles, "WorldsPage.tsx must exist").toContain("WorldsPage.tsx");

describe("WEB_5_worlds_static: the page folder", () => {
  it("WEB_5_worlds_static_has_the_named_page_and_a_stylesheet_and_no_default_export", () => {
    expect(files).toContain("WorldsPage.tsx");
    expect(cssFiles.length).toBeGreaterThan(0);
    expect(code("WorldsPage.tsx")).toMatch(/export\s+(?:function|const)\s+WorldsPage\b/);
    expect(code("WorldsPage.tsx")).not.toMatch(/export\s+default\b/);
  });

  it("WEB_5_worlds_static_imports_nothing_from_screens_world_or_stage", () => {
    built();
    const specs = tsFiles.flatMap((f) =>
      [...code(f).matchAll(/(?:from|import)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] ?? ""),
    );
    expect(specs.filter((s) => /(^|\/)(screens|world|stage)(\/|$)/.test(s))).toEqual([]);
    expect(specs.filter((s) => /support\.js/.test(s))).toEqual([]);
  });

  it.each([
    [
      "window globals and the address bar",
      /\bwindow\b|\bglobalThis\b|\blocation\b|\bdocument\.(?:location|cookie)\b|\bhistory\./,
    ],
    [
      "timers and frames",
      /\b(?:setInterval|setTimeout|requestAnimationFrame|requestIdleCallback)\b/,
    ],
    [
      "motion in code or inline style",
      /\btransition|\banimation|@keyframes|\bwill-change\b|scroll-behavior/i,
    ],
    [
      "any, ts-ignore, raw html",
      /:\s*any\b|\bas\s+any\b|<any>|any\[\]|@ts-(?:ignore|nocheck)|dangerouslySetInnerHTML|\.innerHTML\b/,
    ],
    [
      "a model id or a network call",
      /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-|\bfetch\s*\(|XMLHttpRequest|\beval\s*\(/i,
    ],
  ])("WEB_5_worlds_static_no_%s", (_what, pattern) => {
    built();
    expect(sources.filter((f) => pattern.test(code(f)))).toEqual([]);
  });

  it("WEB_5_worlds_static_the_honesty_scan_finds_nothing", () => {
    built();
    const hits = sources.flatMap((f) => scanSource(`src/park/pages/Worlds/${f}`, read(f)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_5_worlds_static_navigation_and_approval_go_through_the_app_prop_only", () => {
    const page = code("WorldsPage.tsx");
    expect(page).toMatch(/\bgo\(/);
    expect(page).toMatch(/\bdecide\(/);
    expect(page).toMatch(/useParkApi\s*\(/);
    expect(page).toMatch(/getWorlds\s*\(/);
  });
});

describe("WEB_5_worlds_static: the stylesheet", () => {
  it("WEB_5_worlds_static_every_selector_is_under_data_park_and_every_class_is_park_worlds", () => {
    const css = cssFiles.map(read).join("\n");
    const { rules, others } = parseRules(css);
    expect(rules.length).toBeGreaterThan(20);
    expect(
      rules.filter((r) => !r.selector.startsWith("[data-park]")).map((r) => r.selector),
    ).toEqual([]);
    const classes = rules.flatMap((r) =>
      [...r.selector.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1] ?? ""),
    );
    expect(classes.filter((k) => !k.startsWith("park-worlds-"))).toEqual([]);
    expect(
      others.map((o) => o.head),
      "no @keyframes, @font-face or @import",
    ).toEqual([]);
    expect(stripComments(css)).not.toMatch(/data-time|@import/);
  });

  it("WEB_5_worlds_static_the_pages_own_class_names_carry_the_prefix", () => {
    built();
    const names = tsFiles.flatMap((f) =>
      [...code(f).matchAll(/className=\s*"([^"]+)"/g)].flatMap((m) => (m[1] ?? "").split(/\s+/)),
    );
    expect(names.filter((k) => !k.startsWith("park-worlds-"))).toEqual([]);
  });
});

describe("WEB_5_worlds_static: the registry gets one new line", () => {
  const src = readFileSync(join(DIR, "..", "..", "app", "pages.ts"), "utf8");
  // one entry per two-space-indented `key:`; an entry may wrap over several lines, and a lane may leave
  // a whole-line comment (such as a biome-ignore) above its entry
  const entries = [
    ...src.replace(/^ *\/\/.*\n/gm, "").matchAll(/^ {2}(\w+):\s*([\s\S]*?),?\n(?= {2}\w+:|\};)/gm),
  ].map((m) => [m[1], (m[2] ?? "").replace(/\s+/g, " ").trim().replace(/,$/, "")]);

  it("WEB_5_worlds_static_pages_ts_worlds_line_is_the_lazy_import_and_every_other_page_is_untouched_form", () => {
    expect(src).toContain(
      '  worlds: lazy(() => import("../pages/Worlds/WorldsPage").then((m) => ({ default: m.WorldsPage }))),\n',
    );
    expect(entries).toHaveLength(10);
    // another lane's page is its own one line in the same named-export form; the rest stay Placeholder
    const form = /^lazy\(\(\) =>/; // a long line may wrap, so only the opening is checked
    expect(
      entries
        .filter(([k]) => k !== "worlds")
        .every(([, v]) => v === "Placeholder" || form.test(v ?? "")),
    ).toBe(true);
    expect(src).toContain('const Placeholder = lazy(() => import("./Placeholder"));');
  });
});
