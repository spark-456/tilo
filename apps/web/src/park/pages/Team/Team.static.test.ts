// WEB-10 static checks (plan section 10 "Folder per page", "Honesty"; apps/web/src/park/CLAUDE.md):
// - Team.css: every selector under [data-park] with only `park-team-` classes; no transition, animation or
//   @keyframes (the design's tiloFade, .2s colour fades and the 1.8 s flash timer arrive with WEB-3b);
// - the page code: no timers or animation frames, no window/location, no fetch, no direct fixture import
//   (data only through the park Api), no screens/world/stage import, no any / ts-ignore / raw HTML;
// - the amber flash is a rule on [data-flash="true"] with the design's 2px solid #F0A500.
// The helpers testApp.ts and teamExpect.ts are test code and are not scanned.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { scanSource } from "../../../../test-support/honestyScan";
import { parseRules } from "../../../../test-support/park/componentsCss";

const DIR = __dirname;
const CSS = path.join(DIR, "Team.css");
const PAGE = path.join(DIR, "TeamPage.tsx");
const HELPERS = new Set(["testApp.ts", "teamExpect.ts"]);

const pageFiles = (): string[] => {
  expect(existsSync(PAGE), "TeamPage.tsx exists, so there is code to check").toBe(true);
  return readdirSync(DIR)
    .filter((f) => /\.(tsx?|css)$/.test(f) && !/\.test\.tsx?$/.test(f) && !HELPERS.has(f))
    .map((f) => path.join(DIR, f));
};
const code = (p: string): string =>
  readFileSync(p, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

describe("WEB_10_team_files: the page folder", () => {
  it("WEB_10_team_has_TeamPage_tsx_with_a_named_TeamPage_export_and_Team_css", () => {
    expect(existsSync(PAGE), "TeamPage.tsx").toBe(true);
    expect(existsSync(CSS), "Team.css").toBe(true);
    expect(code(PAGE)).toMatch(/export\s+(?:function|const)\s+TeamPage\b/);
    expect(code(PAGE)).not.toMatch(/export\s+default/);
    expect(readFileSync(PAGE, "utf8")).toMatch(/import\s+["']\.\/Team\.css["']/);
  });
});

describe("WEB_10_team_css: scoped, prefixed, motionless", () => {
  it("WEB_10_team_css_every_selector_is_under_data_park_with_park_team_classes_only", () => {
    const { rules } = parseRules(readFileSync(CSS, "utf8"));
    expect(rules.length, "Team.css has rules").toBeGreaterThan(0);
    const bad = rules
      .map((r) => r.selector)
      .filter((s) => {
        if (!s.startsWith("[data-park]")) return true;
        const classes = [...s.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1] as string);
        return classes.length === 0 || classes.some((c) => !c.startsWith("park-team-"));
      });
    expect(
      bad,
      "selectors outside [data-park] or using a class without the park-team- prefix",
    ).toEqual([]);
  });

  it("WEB_10_team_css_has_no_transition_animation_or_keyframes", () => {
    const src = readFileSync(CSS, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(src).not.toMatch(/\btransition\b|\banimation\b|@keyframes|\banimation-/i);
    const { others, rules } = parseRules(src);
    expect(others.map((o) => o.head).filter((h) => /keyframes|import/i.test(h))).toEqual([]);
    const motion = rules
      .flatMap((r) => [...r.decls.keys()])
      .filter((k) => /^(transition|animation)/.test(k));
    expect(motion).toEqual([]);
  });

  it("WEB_10_team_css_flash_is_a_data_flash_rule_with_a_2px_amber_border", () => {
    const { rules } = parseRules(readFileSync(CSS, "utf8"));
    const flash = rules.filter((r) =>
      r.selector.replaceAll("'", '"').includes('[data-flash="true"]'),
    );
    expect(flash.length, "a rule on [data-flash=true]").toBeGreaterThan(0);
    const border = flash
      .map((r) => r.decls.get("border") ?? "")
      .join(" ")
      .toLowerCase();
    expect(border).toContain("2px solid #f0a500");
  });
});

describe("WEB_10_team_honesty: no motion and no clock in the page code", () => {
  it("WEB_10_team_code_has_no_timer_no_animation_frame_no_animation_api", () => {
    const files = pageFiles().filter((f) => /\.tsx?$/.test(f));
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

  it("WEB_10_team_code_passes_the_honesty_scan", () => {
    for (const f of pageFiles().filter((p) => /\.tsx?$/.test(p))) {
      const v = scanSource(`src/park/pages/Team/${path.basename(f)}`, readFileSync(f, "utf8"));
      expect(v.map((x) => `${x.file}:${x.line} ${x.rule}`)).toEqual([]);
    }
  });
});

describe("WEB_10_team_seams: Api in, go() and decide() out", () => {
  it("WEB_10_team_code_reads_no_window_location_and_calls_no_network", () => {
    const hits = pageFiles()
      .filter((f) => /\.tsx?$/.test(f))
      .filter((f) =>
        /\bwindow\s*\.\s*(?:location|history|open)\b|\b(?:document\.)?location\b|\bhistory\.(?:push|replace)State\b|\bfetch\s*\(|\bXMLHttpRequest\b|\bnavigator\.sendBeacon\b/.test(
          code(f),
        ),
      )
      .map((f) => path.basename(f));
    expect(hits, "navigate with app.go, read data through the Api").toEqual([]);
  });

  it("WEB_10_team_code_imports_no_fixtures_directly_and_nothing_from_screens_world_stage", () => {
    const bad: string[] = [];
    for (const f of pageFiles().filter((p) => /\.tsx?$/.test(p))) {
      for (const m of code(f).matchAll(/\b(?:from|import)\s*\(?\s*["']([^"']+)["']/g)) {
        const spec = m[1] as string;
        if (/(^|\/)(screens|world|stage)(\/|$)/.test(spec))
          bad.push(`${path.basename(f)}: ${spec}`);
        if (/api\/fixtures|fixtureApi|liveApi/.test(spec)) bad.push(`${path.basename(f)}: ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("WEB_10_team_code_has_no_any_ts_ignore_raw_html_or_window_global", () => {
    const hits = pageFiles()
      .filter((f) => /\.tsx?$/.test(f))
      .filter((f) =>
        /:\s*any\b|\bas\s+any\b|<any>|@ts-ignore|@ts-nocheck|dangerouslySetInnerHTML|\.innerHTML\b|\beval\s*\(|support\.js/.test(
          readFileSync(f, "utf8"),
        ),
      )
      .map((f) => path.basename(f));
    expect(hits).toEqual([]);
  });

  it("WEB_10_team_does_not_hide_or_replace_the_shell_sample_data_chip", () => {
    // The shell owns the "Sample data" chip (plan section 10). The page neither renders its own copy of it
    // nor targets it: no "Sample data" text, no selector that could hide the shell's chip.
    for (const f of pageFiles()) {
      const src = readFileSync(f, "utf8");
      expect(src, path.basename(f)).not.toMatch(/Sample data|park-sample|data-sample/i);
    }
  });
});
