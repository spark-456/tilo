// WEB-8a style spec: Skills.css is parsed and checked against the numbers of the reference page
// (design_handoff_tilo_web_app/design/Tilo App Skills.dc.html: inline styles and the `renderVals` colours,
// measured as computed values at 1440 x 900 day and night and 390 x 844 and listed in e2e/park-skills.spec.ts).
// Each row below is one rule's worth of the reference: the declarations that sit together on one element. The
// stylesheet may name its classes and spread rules as it likes, but a row passes only when ONE rule of
// Skills.css holds every declaration of one of the row's alternatives (the real cascade, down to computed
// values, is checked in the browser by the e2e spec). Conventions of the Park pages (plan section 10): every
// selector under [data-park] and tied to the page by a `park-skills-` class, colours as var(--token) except the
// few the design hard-codes, no transition / animation / @keyframes (BQ-WEB-3: the recording dot, the spinners
// and the sliding thumb are drawn still), night comes from the tokens. "Skills sheet gap 30" is the PageSheet's
// `gap` prop (checked in the browser), its 40px bottom padding is a row here.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type CssRule, norm, parseRules } from "../../../../test-support/park/componentsCss";
import { stripComments } from "../../../../test-support/park/css";

const CSS_PATH = join(__dirname, "Skills.css");
const css = () => readFileSync(CSS_PATH, "utf8");
const parsed = () => parseRules(css());

type Decls = Readonly<Record<string, string>>;
type Row = readonly [what: string, ...alternatives: Decls[]];

const holds = (rule: CssRule, prop: string, value: string): boolean => {
  const props = prop === "background" ? ["background", "background-color"] : [prop];
  return props.some((p) => rule.decls.has(p) && norm(rule.decls.get(p)) === norm(value));
};
const rowHolds = (rules: readonly CssRule[], alt: Decls): boolean =>
  rules.some((r) => Object.entries(alt).every(([p, v]) => holds(r, p, v)));
const missing = (rules: readonly CssRule[], rows: readonly Row[]): string[] =>
  rows
    .filter(([, ...alts]) => !alts.some((a) => rowHolds(rules, a)))
    .map(([what, ...alts]) => `${what}: ${JSON.stringify(alts[0])}`);

const FLEX = { display: "flex" } as const;
const COL = { display: "flex", "flex-direction": "column" } as const;
const FIT = (px: number) => `repeat(auto-fit, minmax(min(100%, ${px}px), 1fr))`;

const HEADER: readonly Row[] = [
  ["sheet bottom padding", { padding: "28px 32px 40px" }, { "padding-bottom": "40px" }],
  ["title row", { ...FLEX, "align-items": "baseline", gap: "12px" }],
  [
    "h1",
    {
      "font-size": "36px",
      "font-weight": "900",
      "letter-spacing": "-0.8px",
      "line-height": "1.05",
    },
  ],
  ["total", { "font-size": "15px", "font-weight": "700", color: "var(--ink3)" }],
  ["intro", { "font-size": "15.5px", "font-weight": "600", color: "var(--ink2)" }],
  ["intro column", { ...COL, gap: "6px", "max-width": "640px" }],
  [
    "header bar",
    {
      "align-items": "flex-end",
      "justify-content": "space-between",
      gap: "20px",
      "flex-wrap": "wrap",
    },
  ],
  ["pills and button", { ...FLEX, gap: "8px", "align-items": "center", "flex-wrap": "wrap" }],
  [
    "pill",
    {
      height: "30px",
      padding: "0 12px",
      "border-radius": "999px",
      "font-size": "13.5px",
      "font-weight": "800",
    },
  ],
  ["pill trusted", { background: "var(--okSoft)", color: "var(--okInk)" }],
  ["pill learning", { background: "var(--heroSoft)", color: "var(--heroInk)" }],
  ["pill need your help", { background: "var(--amberTile)", color: "var(--amberInk)" }],
  ["pill nothing waiting", { background: "var(--chip)", color: "var(--ink2)" }],
  [
    "Teach a skill button",
    {
      height: "42px",
      padding: "0 18px 0 14px",
      "border-radius": "12px",
      background: "var(--heroFill)",
      color: "#FFFFFF",
      "font-size": "15px",
      "font-weight": "800",
      gap: "8px",
    },
  ],
];

const CARD: readonly Row[] = [
  [
    "card",
    {
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "24px",
      overflow: "hidden",
    },
  ],
  [
    "card head",
    {
      ...FLEX,
      gap: "18px",
      "align-items": "center",
      padding: "20px 24px 18px",
      "border-bottom": "1px solid var(--line2)",
      "flex-wrap": "wrap",
    },
  ],
  [
    "teacher tile",
    {
      width: "64px",
      height: "64px",
      "border-radius": "20px",
      background: "var(--heroSoft)",
      overflow: "hidden",
    },
  ],
  [
    "card title",
    {
      "font-size": "24px",
      "font-weight": "900",
      "letter-spacing": "-0.4px",
      "line-height": "1.15",
    },
  ],
  [
    "card line",
    {
      "font-size": "14.5px",
      "font-weight": "600",
      color: "var(--ink2)",
      "margin-top": "4px",
      "line-height": "1.45",
    },
  ],
  [
    "step bar",
    {
      display: "grid",
      "grid-template-columns": "repeat(4, minmax(0, 1fr))",
      gap: "10px",
      "list-style": "none",
    },
  ],
  ["step button", { ...COL, gap: "8px", "align-items": "flex-start", "text-align": "left" }],
  ["step segment", { height: "5px", "border-radius": "99px" }],
  [
    "step label",
    {
      ...FLEX,
      gap: "7px",
      "align-items": "center",
      "font-size": "13px",
      "font-weight": "800",
      "white-space": "nowrap",
    },
  ],
  ["step dot", { width: "20px", height: "20px", "border-radius": "99px", "font-size": "11.5px" }],
  ["locked step", { opacity: "0.5" }],
  ["step done", { background: "var(--ok)" }],
  ["step current", { background: "var(--hero)" }],
  ["step to come", { background: "var(--track)" }],
];

const SHOW: readonly Row[] = [
  ["show pane", { ...COL, padding: "22px 24px 24px", gap: "18px" }],
  ["method grid", { display: "grid", "grid-template-columns": FIT(210), gap: "10px" }],
  [
    "method tile",
    {
      ...FLEX,
      gap: "12px",
      "align-items": "flex-start",
      padding: "13px 14px",
      "border-radius": "16px",
      "text-align": "left",
    },
  ],
  ["method border", { border: "2px solid var(--line)" }, { "border-width": "2px" }],
  [
    "method chosen",
    { background: "var(--heroSoft)", "border-color": "var(--hero)" },
    { background: "var(--heroSoft)", border: "2px solid var(--hero)" },
  ],
  ["method icon", { width: "36px", height: "36px", "border-radius": "11px" }],
  ["method icon chosen", { background: "var(--card)", color: "var(--heroInk)" }],
  ["method icon idle", { background: "var(--sunk)", color: "var(--ink2)" }],
  ["method name", { "font-size": "14.5px", "font-weight": "800" }],
  ["method line", { "font-size": "13px", color: "var(--ink2)", "font-weight": "600" }],
  [
    "two columns",
    { display: "grid", "grid-template-columns": FIT(400), gap: "18px", "align-items": "stretch" },
  ],
  [
    "mock browser",
    {
      "min-height": "290px",
      background: "var(--toast)",
      color: "var(--toastInk)",
      "border-radius": "20px",
      overflow: "hidden",
    },
  ],
  [
    "mock bar",
    {
      height: "40px",
      padding: "0 14px",
      gap: "7px",
      "border-bottom": "1px solid rgba(127,127,140,.25)",
    },
  ],
  ["mock light", { width: "10px", height: "10px", "border-radius": "99px" }],
  ["mock light red", { background: "#E2483D" }],
  ["mock light amber", { background: "#F0A500" }],
  ["mock light green", { background: "#3BB273" }],
  [
    "mock address",
    {
      height: "24px",
      "border-radius": "8px",
      background: "rgba(127,127,140,.2)",
      "font-size": "12.5px",
      "font-weight": "700",
      padding: "0 10px",
      opacity: "0.85",
    },
  ],
  [
    "mock row",
    {
      height: "38px",
      "border-radius": "12px",
      background: "rgba(127,127,140,.16)",
      gap: "10px",
      padding: "0 12px",
    },
  ],
  ["mock row being watched", { "box-shadow": "0 0 0 3px #F0A500" }],
  [
    "mock footer",
    { padding: "12px 14px", gap: "12px", "border-top": "1px solid rgba(127,127,140,.25)" },
  ],
  ["mock hint", { "font-size": "13.5px", "font-weight": "700", opacity: "0.8" }],
  [
    "capture button",
    {
      height: "40px",
      padding: "0 16px",
      "border-radius": "12px",
      "font-size": "14.5px",
      "font-weight": "800",
      gap: "8px",
    },
  ],
  ["capture idle", { background: "#5A3FE0", color: "#FFFFFF" }],
  ["capture done", { background: "#1E8A4C" }],
  ["capture recording", { background: "var(--red)" }],
  ["REC label", { gap: "8px", "font-size": "13.5px", "font-weight": "800" }],
  ["REC dot", { width: "10px", height: "10px", "border-radius": "99px", background: "#E2483D" }],
  [
    "picked up panel",
    {
      ...COL,
      background: "var(--sunk)",
      "border-radius": "20px",
      padding: "16px 18px",
      gap: "10px",
    },
  ],
  ["picked up title", { "font-size": "15px", "font-weight": "800" }],
  ["picked up count", { "font-size": "13px", "font-weight": "800", color: "var(--ink2)" }],
  [
    "captured step",
    {
      display: "grid",
      "grid-template-columns": "26px minmax(0, 1fr)",
      gap: "12px",
      background: "var(--card)",
      "border-radius": "14px",
      padding: "11px 13px",
    },
  ],
  [
    "captured number",
    {
      width: "26px",
      height: "26px",
      "border-radius": "9px",
      background: "var(--heroSoft)",
      color: "var(--heroInk)",
      "font-size": "12.5px",
      "font-weight": "800",
    },
  ],
  [
    "captured text",
    { "font-size": "14px", "font-weight": "700", "line-height": "1.4", "padding-top": "3px" },
  ],
  [
    "nothing yet",
    {
      padding: "16px",
      gap: "6px",
      "text-align": "center",
      color: "var(--ink2)",
      "font-size": "14px",
      "font-weight": "600",
    },
  ],
  [
    "name field",
    {
      border: "1px solid var(--line)",
      "border-radius": "12px",
      background: "var(--field)",
      padding: "0 14px",
      "font-size": "15px",
      "font-weight": "700",
      color: "var(--ink)",
    },
  ],
  [
    "next button",
    { height: "46px", "border-radius": "13px", "font-size": "15px", "font-weight": "800" },
  ],
  ["next ready", { background: "var(--heroFill)", color: "#FFFFFF" }],
  ["next locked", { background: "var(--track)", color: "var(--ink2)" }],
  [
    "task field",
    {
      "min-height": "210px",
      resize: "none",
      border: "1px solid var(--line)",
      "border-radius": "18px",
      background: "var(--field)",
      padding: "16px 18px",
      "font-size": "15px",
      "line-height": "1.55",
      "font-weight": "600",
    },
  ],
  ["describe help", { "font-size": "13px", color: "var(--ink2)", "font-weight": "600" }],
  [
    "read button",
    {
      height: "40px",
      padding: "0 16px",
      "border-radius": "12px",
      background: "var(--heroFill)",
      color: "#FFFFFF",
      "font-size": "14.5px",
      "font-weight": "800",
    },
  ],
  [
    "dropzone",
    {
      "min-height": "290px",
      border: "2px dashed var(--line)",
      "border-radius": "20px",
      background: "var(--sunk)",
      gap: "10px",
      padding: "24px",
    },
  ],
  [
    "dropzone done",
    { border: "2px dashed var(--ok)", background: "var(--okSoft)" },
    { "border-color": "var(--ok)", background: "var(--okSoft)" },
  ],
  [
    "drop icon",
    {
      width: "52px",
      height: "52px",
      "border-radius": "16px",
      background: "var(--card)",
      color: "var(--heroInk)",
    },
  ],
  ["drop title", { "font-size": "17px", "font-weight": "800" }],
  [
    "drop line",
    {
      "font-size": "13.5px",
      color: "var(--ink2)",
      "font-weight": "600",
      "max-width": "340px",
      "line-height": "1.45",
    },
  ],
];

const LEARN: readonly Row[] = [
  ["learn pane", { display: "grid", "grid-template-columns": FIT(400), gap: "22px" }],
  [
    "bubble tile",
    { width: "44px", height: "44px", "border-radius": "14px", background: "var(--heroSoft)" },
  ],
  [
    "bubble",
    {
      background: "var(--heroSoft)",
      "border-radius": "4px 18px 18px 18px",
      padding: "11px 15px",
      "font-size": "14.5px",
      "font-weight": "600",
      "line-height": "1.45",
    },
  ],
  [
    "plan row",
    {
      display: "grid",
      "grid-template-columns": "28px minmax(0, 1fr) auto",
      gap: "12px",
      "align-items": "center",
      border: "1px solid var(--line)",
      "border-radius": "16px",
      padding: "11px 13px",
    },
  ],
  [
    "plan number",
    {
      width: "28px",
      height: "28px",
      "border-radius": "9px",
      background: "var(--sunk)",
      "font-size": "12.5px",
      "font-weight": "800",
    },
  ],
  ["plan text", { "font-size": "14.5px", "font-weight": "800" }],
  [
    "plan tool",
    {
      ...FLEX,
      gap: "6px",
      "align-items": "center",
      "font-size": "12.5px",
      color: "var(--ink2)",
      "font-weight": "700",
      "margin-top": "3px",
    },
  ],
  [
    "ask switch",
    {
      ...FLEX,
      gap: "8px",
      "align-items": "center",
      "font-size": "12.5px",
      "font-weight": "800",
      "white-space": "nowrap",
    },
  ],
  ["ask switch on", { color: "var(--amberInk)" }],
  ["ask track", { width: "40px", height: "24px", "border-radius": "999px", padding: "3px" }],
  ["ask track on", { background: "#F0A500" }],
  ["ask track off", { background: "var(--track)" }],
  [
    "ask knob",
    {
      width: "18px",
      height: "18px",
      "border-radius": "999px",
      background: "#FFFFFF",
      "box-shadow": "0 1px 2px rgba(0,0,0,.2)",
    },
  ],
  ["ask knob on", { transform: "translateX(16px)" }],
  [
    "question card",
    {
      ...COL,
      background: "var(--amberSoft)",
      border: "1px solid var(--amberLine)",
      "border-radius": "18px",
      padding: "14px 16px",
      gap: "12px",
    },
  ],
  [
    "question tile",
    { width: "42px", height: "42px", "border-radius": "13px", background: "var(--card)" },
  ],
  [
    "question eyebrow",
    {
      "font-size": "12px",
      "font-weight": "800",
      color: "var(--amberInk)",
      "letter-spacing": "0.5px",
    },
  ],
  ["question text", { "font-size": "15px", "font-weight": "800" }],
  [
    "answer pill",
    {
      height: "36px",
      padding: "0 13px",
      "border-radius": "999px",
      "font-size": "13.5px",
      "font-weight": "800",
      "white-space": "nowrap",
    },
  ],
  ["answer chosen", { background: "var(--toast)", color: "var(--toastInk)" }],
  [
    "estimates",
    { display: "grid", "grid-template-columns": "repeat(3, minmax(0, 1fr))", gap: "8px" },
  ],
  [
    "estimate",
    {
      background: "var(--sunk)",
      "border-radius": "14px",
      padding: "10px 13px",
      "line-height": "1.3",
    },
  ],
  ["estimate label", { "font-size": "12px", "font-weight": "700", color: "var(--ink3)" }],
  ["estimate value", { "font-size": "18px", "font-weight": "800" }],
  [
    "learn note",
    { "font-size": "13.5px", color: "var(--ink2)", "font-weight": "600", "line-height": "1.5" },
  ],
  [
    "back button",
    {
      height: "44px",
      padding: "0 18px",
      "border-radius": "12px",
      background: "var(--btn2)",
      border: "1px solid var(--line)",
      "font-size": "14.5px",
      "font-weight": "800",
    },
  ],
  [
    "go button",
    {
      height: "44px",
      "border-radius": "12px",
      background: "var(--heroFill)",
      color: "#FFFFFF",
      "font-size": "15px",
      "font-weight": "800",
    },
  ],
];

const RUN: readonly Row[] = [
  [
    "art panel",
    {
      "min-height": "300px",
      background: "var(--heroSoft)",
      "border-radius": "22px",
      padding: "0 20px 30px",
      gap: "4px",
      overflow: "hidden",
      position: "relative",
    },
  ],
  ["art panel top row", { position: "absolute", left: "16px", top: "16px", right: "16px" }],
  [
    "art panel pill",
    {
      height: "30px",
      padding: "0 12px",
      "border-radius": "999px",
      background: "var(--card)",
      "font-size": "13px",
      "font-weight": "800",
    },
  ],
  [
    "run step",
    {
      ...COL,
      border: "1px solid var(--line)",
      "border-radius": "16px",
      padding: "11px 13px",
      gap: "10px",
    },
  ],
  [
    "run step line",
    {
      display: "grid",
      "grid-template-columns": "28px minmax(0, 1fr) auto",
      gap: "12px",
      "align-items": "center",
    },
  ],
  [
    "run dot",
    {
      width: "28px",
      height: "28px",
      "border-radius": "99px",
      "font-size": "12.5px",
      "font-weight": "800",
    },
  ],
  ["run text", { "font-size": "14.5px", "font-weight": "800", "line-height": "1.35" }],
  ["run status", { "font-size": "12.5px", "font-weight": "800", "white-space": "nowrap" }],
  ["run step working", { background: "var(--heroSoft)" }],
  [
    "run step asking",
    { background: "var(--amberSoft)", "border-color": "var(--amberLine)" },
    { background: "var(--amberSoft)", border: "1px solid var(--amberLine)" },
  ],
  ["run dot done", { background: "var(--ok)" }],
  ["run dot asking", { background: "#F0A500" }],
  ["run status done", { color: "var(--okInk)" }],
  ["run status asking", { color: "var(--amberInk)" }],
  ["run status working", { color: "var(--heroInk)" }],
  ["run status waiting", { color: "var(--ink3)" }],
  [
    "answer row",
    { ...FLEX, gap: "10px", "align-items": "center", "flex-wrap": "wrap", "padding-left": "40px" },
  ],
  ["answer prompt", { "font-size": "13.5px", "font-weight": "600", color: "var(--ink2)" }],
  [
    "yes button",
    {
      height: "36px",
      padding: "0 14px",
      "border-radius": "11px",
      background: "#F0A500",
      color: "#1F1D2B",
      "font-weight": "800",
      "font-size": "14px",
    },
  ],
  [
    "result",
    {
      ...FLEX,
      background: "var(--okSoft)",
      "border-radius": "18px",
      padding: "13px 15px",
      gap: "12px",
      "align-items": "center",
      "flex-wrap": "wrap",
    },
  ],
  ["result title", { "font-weight": "800", "font-size": "15px", color: "var(--okInk)" }],
  ["result line", { "font-size": "13.5px", color: "var(--okInk)", "font-weight": "600" }],
  [
    "fix button",
    {
      height: "40px",
      padding: "0 14px",
      "border-radius": "12px",
      background: "var(--btn2)",
      border: "1px solid var(--line)",
      "font-size": "14px",
      "font-weight": "800",
    },
  ],
  [
    "looks right button",
    {
      height: "40px",
      padding: "0 16px",
      "border-radius": "12px",
      background: "var(--heroFill)",
      color: "#FFFFFF",
      "font-size": "14px",
      "font-weight": "800",
    },
  ],
];

const SAVE: readonly Row[] = [
  ["form label", { "font-size": "13px", "font-weight": "800", color: "var(--ink2)" }],
  [
    "save name field",
    {
      height: "46px",
      border: "1px solid var(--line)",
      "border-radius": "12px",
      background: "var(--field)",
      padding: "0 14px",
      "font-size": "16px",
      "font-weight": "800",
    },
  ],
  [
    "picker track",
    {
      ...FLEX,
      gap: "2px",
      padding: "3px",
      "border-radius": "12px",
      background: "var(--seg)",
      "flex-wrap": "wrap",
    },
  ],
  [
    "picker item",
    {
      flex: "1",
      height: "36px",
      padding: "0 14px",
      "border-radius": "9px",
      "font-size": "14px",
      "font-weight": "800",
      "white-space": "nowrap",
    },
  ],
  [
    "picker item chosen",
    {
      background: "var(--tabOn)",
      "box-shadow": "0 1px 3px rgba(31,29,43,.16)",
      color: "var(--ink)",
    },
  ],
  [
    "starts as card",
    {
      ...FLEX,
      background: "var(--heroSoft)",
      "border-radius": "18px",
      padding: "14px 16px",
      gap: "14px",
      "align-items": "center",
    },
  ],
  [
    "starts as tile",
    { width: "48px", height: "48px", "border-radius": "15px", background: "var(--card)" },
  ],
  ["starts as text", { "font-size": "14px", "font-weight": "600", "line-height": "1.45" }],
  [
    "saved banner",
    {
      ...FLEX,
      "grid-column": "1 / -1",
      gap: "20px",
      background: "var(--okSoft)",
      "border-radius": "22px",
      padding: "18px 22px",
      "align-items": "center",
      "flex-wrap": "wrap",
    },
  ],
  [
    "saved tile",
    { width: "76px", height: "76px", "border-radius": "22px", background: "var(--card)" },
  ],
  ["saved title", { "font-weight": "900", "font-size": "22px", color: "var(--okInk)" }],
  ["saved line", { "font-size": "14.5px", color: "var(--okInk)", "font-weight": "600" }],
  [
    "view and another",
    {
      height: "42px",
      padding: "0 16px",
      "border-radius": "12px",
      "font-size": "14.5px",
      "font-weight": "800",
    },
  ],
];

describe("WEB_8a_styles: Skills.css exists and follows the Park conventions", () => {
  it("WEB_8a_styles_Skills_css_exists_and_SkillsPage_imports_it", () => {
    expect(existsSync(CSS_PATH), "src/park/pages/Skills/Skills.css").toBe(true);
    const page = readFileSync(join(__dirname, "SkillsPage.tsx"), "utf8");
    expect(page).toMatch(/import\s+["']\.\/Skills\.css["']/);
  });

  it("WEB_8a_styles_every_selector_is_under_data_park_and_tied_to_a_park_skills_class", () => {
    const { rules } = parsed();
    expect(rules.length).toBeGreaterThan(40);
    for (const r of rules) {
      expect(r.selector, r.selector).toMatch(/^\[data-park\]/);
      expect(r.selector, `${r.selector} must carry a park-skills- class`).toMatch(
        /\.park-skills-[\w-]+/,
      );
    }
  });

  it("WEB_8a_styles_no_transition_animation_keyframes_or_will_change", () => {
    expect(stripComments(css())).not.toMatch(
      /\btransition\b|\banimation\b|@keyframes|will-change/i,
    );
    expect(parsed().others.map((o) => o.head)).toEqual([]);
  });

  it("WEB_8a_styles_colours_are_tokens_except_the_ones_the_design_hard_codes", () => {
    const text = stripComments(css());
    const hex = [...text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toUpperCase());
    // #F0A500 / #1F1D2B (needs), #FFFFFF (on hero), #5A3FE0 (capture button and the focus ring), #1E8A4C (captured),
    // #E2483D and #3BB273 (the mock browser's lights): the reference's own inline colours.
    const allowed = ["#F0A500", "#1F1D2B", "#FFFFFF", "#5A3FE0", "#1E8A4C", "#E2483D", "#3BB273"];
    for (const h of hex) expect(allowed, `hard-coded ${h}`).toContain(h);
    const rgb = [...text.matchAll(/rgba?\([^)]*\)/g)].map((m) => norm(m[0]));
    const okRgb = [
      "rgba(127,127,140,.4)",
      "rgba(127,127,140,.32)",
      "rgba(127,127,140,.3)",
      "rgba(127,127,140,.25)",
      "rgba(127,127,140,.2)",
      "rgba(127,127,140,.16)",
      "rgba(31,29,43,.16)",
      "rgba(0,0,0,.2)",
    ];
    expect(rgb.filter((c) => !okRgb.includes(c))).toEqual([]);
  });

  it("WEB_8a_styles_night_comes_from_the_tokens_not_from_overrides_here", () => {
    expect(stripComments(css())).not.toMatch(/data-time/);
  });
});

describe("WEB_8a_styles: every value of the reference's inline styles", () => {
  const rules = () => parsed().rules;

  it("WEB_8a_styles_the_header_h1_is_Nunito_900_and_the_card_titles_are_Nunito_too", () => {
    const titles = rules().filter(
      (r) =>
        norm(r.decls.get("font-size")) === "36px" && norm(r.decls.get("font-weight")) === "900",
    );
    expect(titles.length).toBeGreaterThanOrEqual(1);
    for (const sizeOfTitle of ["24px", "22px"]) {
      const hit = rules().filter(
        (r) =>
          norm(r.decls.get("font-size")) === sizeOfTitle &&
          norm(r.decls.get("font-weight")) === "900",
      );
      expect(hit.length, `a ${sizeOfTitle} title rule`).toBeGreaterThanOrEqual(1);
      expect(hit.some((r) => /nunito(?! sans)/.test(norm(r.decls.get("font-family"))))).toBe(true);
    }
    expect(titles.some((r) => /nunito(?! sans)/.test(norm(r.decls.get("font-family"))))).toBe(true);
  });

  it("WEB_8a_styles_header_and_pills", () => {
    expect(missing(rules(), HEADER)).toEqual([]);
  });

  it("WEB_8a_styles_the_card_its_head_and_the_step_bar", () => {
    expect(missing(rules(), CARD)).toEqual([]);
  });

  it("WEB_8a_styles_step_1_methods_the_mock_browser_what_Tilo_picked_up_describe_and_upload", () => {
    expect(missing(rules(), SHOW)).toEqual([]);
  });

  it("WEB_8a_styles_step_2_the_plan_the_switches_the_question_and_the_estimates", () => {
    expect(missing(rules(), LEARN)).toEqual([]);
  });

  it("WEB_8a_styles_step_3_the_practice_run", () => {
    expect(missing(rules(), RUN)).toEqual([]);
  });

  it("WEB_8a_styles_step_4_save_and_the_saved_banner", () => {
    expect(missing(rules(), SAVE)).toEqual([]);
  });

  it("WEB_8a_styles_hover_and_focus_are_states_not_motion", () => {
    const hover = rules().filter((r) => /:hover/.test(r.selector));
    expect(rowHolds(hover, { filter: "brightness(1.08)" })).toBe(true); // Teach a skill
    const focus = rules().filter((r) => /:focus-visible/.test(r.selector));
    // README Interactions: 3px #5A3FE0, offset 2px, on every control of the page.
    expect(
      focus.some(
        (r) => holds(r, "outline", "3px solid #5A3FE0") && holds(r, "outline-offset", "2px"),
      ),
    ).toBe(true);
  });

  it("WEB_8a_styles_narrow_layouts_come_from_auto_fit_grids_and_wrapping_not_fixed_widths", () => {
    // The reference is fluid (min(100%, 210/400px) columns, wrap): nothing in the card is a fixed pixel width
    // wider than a phone (the widest fixed value is the 340px cap of the drop line).
    const wide = rules().flatMap((r) =>
      ["width", "min-width"].flatMap((p) => {
        const v = r.decls.get(p);
        const n = v && /^\d+(\.\d+)?px$/.test(v.trim()) ? Number.parseFloat(v) : 0;
        return n > 340 ? [`${r.selector} ${p}: ${v}`] : [];
      }),
    );
    expect(wide).toEqual([]);
  });
});
