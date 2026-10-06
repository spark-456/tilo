// WEB-11 stylesheet and source checks (plan section 10 "Folder per page", "Honesty"; design reference
// `Tilo App Connectors.dc.html`):
// - Connectors.css: every selector under `[data-park]`, every class prefixed `park-connectors-`, no
//   transition, animation or @keyframes (motion arrives with WEB-3b, BQ-WEB-3);
// - the numbers of the reference: each row below names the inline-style text of the .dc.html it comes
//   from (checked to exist there) and the declarations one rule of Connectors.css must carry. PageSheet's
//   gap of 22 is checked on the rendered page (Connectors.render.test.tsx), where the sheet is a
//   component. Colours are tokens (var(--...)) and are not pinned here;
// - source: no timer or rAF, no fixtures import (data only through the Api), no window.location.
// The reader is test-support/park/componentsCss.ts (comments, rules, @media flattened).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { norm, parseRules } from "../../../../test-support/park/componentsCss";
import { stripComments } from "../../../../test-support/park/css";
import { HANDOFF_DIR } from "../../../../test-support/park/prototype";

const DIR = __dirname;
const CSS_FILE = path.join(DIR, "Connectors.css");
const REFERENCE = fs.readFileSync(
  path.join(HANDOFF_DIR, "design", "Tilo App Connectors.dc.html"),
  "utf8",
);
const cssText = (): string => fs.readFileSync(CSS_FILE, "utf8");

describe("WEB_11_connectors_css: selectors, prefix, no motion", () => {
  it("WEB_11_connectors_css_file_exists_and_has_rules", () => {
    expect(fs.existsSync(CSS_FILE), "apps/web/src/park/pages/Connectors/Connectors.css").toBe(true);
    expect(parseRules(cssText()).rules.length).toBeGreaterThan(20);
  });

  it("WEB_11_connectors_css_every_selector_is_under_data_park_with_the_park_connectors_prefix", () => {
    const { rules } = parseRules(cssText());
    const bad = rules
      .filter((r) => {
        const classes = [...r.selector.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1] as string);
        const under = r.selector.startsWith("[data-park] ");
        return (
          !under || classes.length === 0 || classes.some((c) => !c.startsWith("park-connectors-"))
        );
      })
      .map((r) => r.selector);
    expect(bad).toEqual([]);
  });

  it("WEB_11_connectors_css_has_no_transition_animation_or_keyframes", () => {
    const css = stripComments(cssText());
    expect(css).not.toMatch(/@keyframes/i);
    expect(css).not.toMatch(/(^|[;{\s])(transition|animation)[\w-]*\s*:/i);
    expect(parseRules(cssText()).others).toEqual([]);
  });
});

interface Row {
  what: string;
  /** Inline-style text of the reference this row comes from. */
  ref: string[];
  /** Declarations one rule must carry (values compared after normalisation). */
  decls: Record<string, string>;
}

const ROWS: Row[] = [
  {
    what: "h1",
    ref: ["font-weight:900;font-size:36px;letter-spacing:-.8px;line-height:1.05"],
    decls: {
      "font-size": "36px",
      "font-weight": "900",
      "letter-spacing": "-0.8px",
      "line-height": "1.05",
    },
  },
  {
    what: "subtitle",
    ref: ["font-size:15.5px;font-weight:600;color:var(--ink2)"],
    decls: { "font-size": "15.5px", "font-weight": "600" },
  },
  {
    what: "search field",
    ref: [
      "height:42px;width:260px;box-sizing:border-box;border-radius:12px;background:var(--field);border:1px solid var(--line);display:flex;align-items:center;gap:8px;padding:0 12px",
    ],
    decls: {
      height: "42px",
      width: "260px",
      "border-radius": "12px",
      gap: "8px",
      padding: "0 12px",
    },
  },
  {
    what: "search input",
    ref: ["font-size:14.5px;font-weight:600;color:var(--ink)"],
    decls: { "font-size": "14.5px", "font-weight": "600" },
  },
  {
    what: "attention banner",
    ref: ["gap:14px;padding:12px 14px 12px 12px;border-radius:18px;background:var(--redSoft)"],
    decls: { gap: "14px", padding: "12px 14px 12px 12px", "border-radius": "18px" },
  },
  {
    what: "banner icon tile",
    ref: ["width:40px;height:40px;border-radius:12px;background:var(--card);color:var(--red)"],
    decls: { width: "40px", height: "40px", "border-radius": "12px" },
  },
  {
    what: "banner title",
    ref: ['font-size:15px;font-weight:800">HubSpot sign-in'],
    decls: { "font-size": "15px", "font-weight": "800" },
  },
  {
    what: "banner sub",
    ref: ['font-size:13.5px;font-weight:600;color:var(--ink2)">Scan competitor'],
    decls: { "font-size": "13.5px", "font-weight": "600" },
  },
  {
    what: "reconnect button",
    ref: ["height:38px;padding:0 16px;border:0;border-radius:11px;background:var(--red)"],
    decls: {
      height: "38px",
      padding: "0 16px",
      "border-radius": "11px",
      "font-size": "14px",
      "font-weight": "800",
    },
  },
  {
    what: "section title",
    ref: ['font-size:16px;font-weight:800">Connected'],
    decls: { "font-size": "16px", "font-weight": "800" },
  },
  {
    what: "section count",
    ref: ["font-size:13.5px;font-weight:700;color:var(--ink3)"],
    decls: { "font-size": "13.5px", "font-weight": "700" },
  },
  {
    what: "connected grid",
    ref: ["grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px"],
    decls: {
      display: "grid",
      "grid-template-columns": "repeat(auto-fill,minmax(290px,1fr))",
      gap: "14px",
    },
  },
  {
    what: "connected tile",
    ref: ["border-radius:20px;padding:16px;display:flex;flex-direction:column;gap:14px"],
    decls: {
      "border-radius": "20px",
      padding: "16px",
      display: "flex",
      "flex-direction": "column",
      gap: "14px",
    },
  },
  {
    what: "connected tile monogram",
    ref: ["width:44px;height:44px;border-radius:13px", "font-size:17px;font-weight:900"],
    decls: {
      width: "44px",
      height: "44px",
      "border-radius": "13px",
      "font-size": "17px",
      "font-weight": "900",
    },
  },
  {
    what: "connected tile account line",
    ref: [
      "font-size:13px;font-weight:600;color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
    ],
    decls: {
      "font-size": "13px",
      "white-space": "nowrap",
      overflow: "hidden",
      "text-overflow": "ellipsis",
    },
  },
  {
    what: "level chip",
    ref: ["height:24px;padding:0 9px;border-radius:7px", "font-size:12px;font-weight:800"],
    decls: {
      height: "24px",
      padding: "0 9px",
      "border-radius": "7px",
      "font-size": "12px",
      "font-weight": "800",
    },
  },
  {
    what: "sync row",
    ref: ["font-size:12.5px;font-weight:700"],
    decls: { "font-size": "12.5px", "font-weight": "700" },
  },
  {
    what: "sync dot",
    ref: ["width:7px;height:7px;border-radius:99px"],
    decls: { width: "7px", height: "7px", "border-radius": "99px" },
  },
  {
    what: "available grid",
    ref: ["grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px"],
    decls: {
      display: "grid",
      "grid-template-columns": "repeat(auto-fill,minmax(300px,1fr))",
      gap: "12px",
    },
  },
  {
    what: "available tile",
    ref: ["border-radius:18px;padding:14px;display:flex;align-items:center;gap:12px"],
    decls: {
      "border-radius": "18px",
      padding: "14px",
      display: "flex",
      "align-items": "center",
      gap: "12px",
    },
  },
  {
    what: "available tile monogram",
    ref: [
      "width:40px;height:40px;border-radius:12px;background:var(--pop)",
      "font-size:15px;font-weight:900",
    ],
    decls: {
      width: "40px",
      height: "40px",
      "border-radius": "12px",
      "font-size": "15px",
      "font-weight": "900",
    },
  },
  {
    what: "connect button",
    ref: ["height:34px;min-width:84px;padding:0 12px;border-radius:10px"],
    decls: {
      height: "34px",
      "min-width": "84px",
      padding: "0 12px",
      "border-radius": "10px",
      "font-size": "13px",
      "font-weight": "800",
    },
  },
  {
    what: "scrim",
    ref: ["position:fixed;inset:0;z-index:34"],
    decls: { position: "fixed", "z-index": "34" },
  },
  {
    what: "drawer",
    ref: [
      "position:fixed;right:16px;top:90px;bottom:16px;width:440px;max-width:calc(100vw - 32px);z-index:35",
      "border-radius:24px",
    ],
    decls: {
      position: "fixed",
      right: "16px",
      top: "90px",
      bottom: "16px",
      width: "440px",
      "max-width": "calc(100vw - 32px)",
      "z-index": "35",
      "border-radius": "24px",
    },
  },
  {
    what: "drawer header",
    ref: ["padding:20px 22px 16px;display:flex;align-items:center;gap:14px"],
    decls: { padding: "20px 22px 16px", gap: "14px" },
  },
  {
    what: "drawer monogram",
    ref: ["width:52px;height:52px;border-radius:15px"],
    decls: {
      width: "52px",
      height: "52px",
      "border-radius": "15px",
      "font-size": "20px",
      "font-weight": "900",
    },
  },
  {
    what: "drawer name",
    ref: ["font-size:19px;font-weight:800"],
    decls: { "font-size": "19px", "font-weight": "800" },
  },
  {
    what: "drawer close button",
    ref: ["width:36px;height:36px;border:0;border-radius:11px"],
    decls: { width: "36px", height: "36px", "border-radius": "11px" },
  },
  {
    what: "drawer status band",
    ref: ["gap:10px;padding:12px 14px;border-radius:14px", "font-size:13.5px;font-weight:700"],
    decls: {
      gap: "10px",
      padding: "12px 14px",
      "border-radius": "14px",
      "font-size": "13.5px",
      "font-weight": "700",
    },
  },
  {
    what: "drawer level row",
    ref: ["gap:12px;padding:12px 14px;border-radius:14px;border:2px solid"],
    decls: { gap: "12px", padding: "12px 14px", "border-radius": "14px" },
  },
  {
    what: "drawer radio ring",
    ref: ["width:18px;height:18px;border-radius:99px;border:2px solid"],
    decls: { width: "18px", height: "18px", "border-radius": "99px" },
  },
  {
    what: "drawer radio dot",
    ref: ["width:8px;height:8px;border-radius:99px"],
    decls: { width: "8px", height: "8px", "border-radius": "99px" },
  },
  {
    what: "drawer used-by row",
    ref: ["gap:10px;height:42px;padding:0 12px;border-radius:12px"],
    decls: { gap: "10px", height: "42px", padding: "0 12px", "border-radius": "12px" },
  },
  {
    what: "drawer footer note",
    ref: ["font-size:12.5px;font-weight:600;color:var(--ink3);line-height:1.5"],
    decls: { "font-size": "12.5px", "font-weight": "600", "line-height": "1.5" },
  },
  {
    what: "drawer footer",
    ref: ["padding:14px 22px;border-top:1px solid var(--line2)"],
    decls: { padding: "14px 22px" },
  },
  {
    what: "disconnect button",
    ref: ["height:40px;padding:0 14px;border:0;border-radius:11px;background:transparent"],
    decls: {
      height: "40px",
      padding: "0 14px",
      "border-radius": "11px",
      "font-size": "14px",
      "font-weight": "800",
    },
  },
  {
    what: "sync now button",
    ref: ["height:40px;padding:0 16px 0 14px;border-radius:11px"],
    decls: { height: "40px", padding: "0 16px 0 14px", "border-radius": "11px", gap: "8px" },
  },
];

describe("WEB_11_connectors_css: values match the reference", () => {
  it("WEB_11_connectors_css_the_rows_are_read_from_the_reference_html", () => {
    const missing = ROWS.flatMap((r) =>
      r.ref.filter((s) => !REFERENCE.includes(s)).map((s) => `${r.what}: ${s}`),
    );
    expect(missing).toEqual([]);
  });

  it.each(ROWS.map((r) => [r.what, r] as const))(
    "WEB_11_connectors_css_values_%s",
    (_what, row) => {
      const { rules } = parseRules(cssText());
      const found = rules.some((r) =>
        Object.entries(row.decls).every(([k, v]) => norm(r.decls.get(k)) === norm(v)),
      );
      expect(found, `one rule of Connectors.css carries ${JSON.stringify(row.decls)}`).toBe(true);
    },
  );
});

describe("WEB_11_connectors_source: honesty and seams", () => {
  const files = (): string[] =>
    fs.existsSync(DIR)
      ? fs
          .readdirSync(DIR)
          .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f) && f !== "testApp.ts")
      : [];
  const code = (f: string): string =>
    fs
      .readFileSync(path.join(DIR, f), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

  it("WEB_11_connectors_source_page_file_exports_ConnectorsPage_and_imports_its_stylesheet", () => {
    expect(files()).toContain("ConnectorsPage.tsx");
    const page = code("ConnectorsPage.tsx");
    expect(page).toMatch(/export\s+(function|const)\s+ConnectorsPage\b/);
    expect(page).toMatch(/import\s+["']\.\/Connectors\.css["']/);
  });

  it("WEB_11_connectors_source_no_timer_no_raf_no_animation_api", () => {
    const banned =
      /\b(setTimeout|setInterval|requestAnimationFrame|requestIdleCallback|clearTimeout|clearInterval)\b|\.animate\s*\(/;
    expect(files().length, "the page folder has source files").toBeGreaterThan(0);
    const hits = files().filter((f) => banned.test(code(f)));
    expect(hits, "timers wait for WEB-3b's reviewed allowlist").toEqual([]);
  });

  it("WEB_11_connectors_source_data_only_through_the_api_and_navigation_only_through_app", () => {
    const hits = files().flatMap((f) => {
      const c = code(f);
      const bad: string[] = [];
      if (/from\s+["'][^"']*api\/fixtures/.test(c)) bad.push(`${f} imports the fixtures directly`);
      if (
        /window\.location|location\.(href|hash|assign|replace)|history\.(push|replace)State/.test(c)
      )
        bad.push(`${f} reads or writes the location`);
      if (/from\s+["'][^"']*\/(screens|world|stage)\//.test(c))
        bad.push(`${f} imports screens/world/stage`);
      if (/dangerouslySetInnerHTML|@ts-ignore|:\s*any\b|\bas\s+any\b|<any>/.test(c))
        bad.push(`${f} uses any, ts-ignore or raw html`);
      return bad;
    });
    expect(hits).toEqual([]);
    expect(files().length).toBeGreaterThan(0);
  });
});
