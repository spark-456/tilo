// WEB-12 static checks (plan section 10 "Folder per page", "Honesty"; apps/web/src/park/CLAUDE.md):
// - Profile.css: every selector under [data-park] with only `park-profile-` classes; no transition,
//   animation or @keyframes (the design's .2s colour fades and the knob's .25s travel arrive with WEB-3b);
// - the page code: no timers or animation frames, no window/location, no fetch, no direct fixture import
//   (data only through useParkApi(), no `api` prop), no screens/world/stage import, no any / ts-ignore /
//   raw HTML;
// - no "Sample data" chip and no "recorded for the demo" line: both are shell-only (WEB-3b).
// The helpers testApp.ts and profileExpect.ts are test code and are not scanned.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { scanSource } from "../../../../test-support/honestyScan";
import { parseRules } from "../../../../test-support/park/componentsCss";

const DIR = __dirname;
const CSS = path.join(DIR, "Profile.css");
const PAGE = path.join(DIR, "ProfilePage.tsx");
const HELPERS = new Set(["testApp.ts", "profileExpect.ts"]);

const pageFiles = (): string[] => {
  expect(existsSync(PAGE), "ProfilePage.tsx exists, so there is code to check").toBe(true);
  return readdirSync(DIR)
    .filter((f) => /\.(tsx?|css)$/.test(f) && !/\.test\.tsx?$/.test(f) && !HELPERS.has(f))
    .map((f) => path.join(DIR, f));
};
const codeFiles = (): string[] => pageFiles().filter((f) => /\.tsx?$/.test(f));
const code = (p: string): string =>
  readFileSync(p, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

describe("WEB_12_profile_files: the page folder", () => {
  it("WEB_12_profile_has_ProfilePage_tsx_with_a_named_ProfilePage_export_and_Profile_css", () => {
    expect(existsSync(PAGE), "ProfilePage.tsx").toBe(true);
    expect(existsSync(CSS), "Profile.css").toBe(true);
    expect(code(PAGE)).toMatch(/export\s+(?:function|const)\s+ProfilePage\b/);
    expect(code(PAGE)).not.toMatch(/export\s+default/);
    expect(readFileSync(PAGE, "utf8")).toMatch(/import\s+["']\.\/Profile\.css["']/);
  });

  it("WEB_12_profile_takes_only_app_and_reads_data_through_useParkApi", () => {
    const src = code(PAGE);
    expect(src, "props are { app } only (AG-WEB ruling)").toMatch(
      /ProfilePage\s*\(\s*\{\s*app\s*\}/,
    );
    expect(src).not.toMatch(/ProfilePage\s*\(\s*\{[^}]*\bapi\b/);
    expect(src, "the Api comes from the provider").toMatch(/\buseParkApi\s*\(/);
    expect(src).toMatch(/from\s+["']\.\.\/\.\.\/app\/(?:context|AppCtx)["']/);
  });
});

describe("WEB_12_profile_css: scoped, prefixed, motionless", () => {
  it("WEB_12_profile_css_every_selector_is_under_data_park_with_park_profile_classes_only", () => {
    const { rules } = parseRules(readFileSync(CSS, "utf8"));
    expect(rules.length, "Profile.css has rules").toBeGreaterThan(0);
    const bad = rules
      .map((r) => r.selector)
      .filter((s) => {
        if (!s.startsWith("[data-park]")) return true;
        const classes = [...s.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1] as string);
        return classes.length === 0 || classes.some((c) => !c.startsWith("park-profile-"));
      });
    expect(
      bad,
      "selectors outside [data-park] or using a class without the park-profile- prefix",
    ).toEqual([]);
  });

  it("WEB_12_profile_css_has_no_transition_animation_or_keyframes", () => {
    const src = readFileSync(CSS, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(src).not.toMatch(/\btransition\b|\banimation\b|@keyframes|\banimation-/i);
    const { others, rules } = parseRules(src);
    expect(others.map((o) => o.head).filter((h) => /keyframes|import/i.test(h))).toEqual([]);
    const motion = rules
      .flatMap((r) => [...r.decls.keys()])
      .filter((k) => /^(transition|animation)/.test(k));
    expect(motion).toEqual([]);
  });
});

describe("WEB_12_profile_honesty: no motion and no clock in the page code", () => {
  it("WEB_12_profile_code_has_no_timer_no_animation_frame_no_animation_api", () => {
    const files = codeFiles();
    expect(files.length).toBeGreaterThan(0);
    const hits = files.flatMap((f) =>
      code(f)
        .split(/\r?\n/)
        .map((line, i) => ({ f: path.basename(f), i: i + 1, line }))
        .filter((l) =>
          /\b(setTimeout|setInterval|requestAnimationFrame|cancelAnimationFrame|queueMicrotask)\b|\.animate\s*\(/.test(
            l.line,
          ),
        )
        .map((l) => `${l.f}:${l.i} ${l.line.trim()}`),
    );
    expect(hits).toEqual([]);
  });

  it("WEB_12_profile_code_passes_the_honesty_scan", () => {
    for (const f of codeFiles()) {
      const v = scanSource(`src/park/pages/Profile/${path.basename(f)}`, readFileSync(f, "utf8"));
      expect(v.map((x) => `${x.file}:${x.line} ${x.rule}`)).toEqual([]);
    }
  });
});

describe("WEB_12_profile_seams: Api in, go() and setPref() out", () => {
  it("WEB_12_profile_code_reads_no_window_location_and_calls_no_network", () => {
    const hits = codeFiles()
      .filter((f) =>
        /\bwindow\s*\.\s*(?:location|history|open)\b|\b(?:document\.)?location\b|\bhistory\.(?:push|replace)State\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bnavigator\.sendBeacon\b/.test(
          code(f),
        ),
      )
      .map((f) => path.basename(f));
    expect(hits, "navigate with app.go, read data through the Api").toEqual([]);
  });

  it("WEB_12_profile_code_imports_no_fixtures_directly_and_nothing_from_screens_world_stage", () => {
    const bad: string[] = [];
    for (const f of codeFiles()) {
      for (const m of code(f).matchAll(/\b(?:from|import)\s*\(?\s*["']([^"']+)["']/g)) {
        const spec = m[1] as string;
        if (/(^|\/)(screens|world|stage)(\/|$)/.test(spec))
          bad.push(`${path.basename(f)}: ${spec}`);
        if (/api\/fixtures|fixtureApi|liveApi/.test(spec)) bad.push(`${path.basename(f)}: ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("WEB_12_profile_code_has_no_any_ts_ignore_raw_html_or_window_global", () => {
    const hits = codeFiles()
      .filter((f) =>
        /:\s*any\b|\bas\s+any\b|<any>|@ts-ignore|@ts-nocheck|dangerouslySetInnerHTML|\.innerHTML\b|\beval\s*\(|support\.js/.test(
          readFileSync(f, "utf8"),
        ),
      )
      .map((f) => path.basename(f));
    expect(hits).toEqual([]);
  });

  it("WEB_12_profile_does_not_render_the_shell_sample_data_chip_or_its_recorded_line", () => {
    // Shell-only (WEB-3b): the page has no "Sample data" chip and no "recorded for the demo" line.
    for (const f of pageFiles()) {
      const src = readFileSync(f, "utf8");
      expect(src, path.basename(f)).not.toMatch(
        /Sample data|recorded for the demo|park-sample|data-sample/i,
      );
    }
  });
});
