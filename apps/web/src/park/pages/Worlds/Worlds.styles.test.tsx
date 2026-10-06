// @vitest-environment happy-dom
// WEB-5 style spec: the pixel values of "Tilo App Worlds.dc.html" (heights, paddings, radii, type, grid minmax,
// card heights 404/196/150), read the way components.styles.test.ts reads park.components.css. The page is
// mounted, each element is found by role or text, and what applies to it is the merge of park.components.css,
// the page stylesheet(s) in this folder and the element's inline style (data-driven values: shadow, dot,
// bar colour). Class names are never pinned. Conventions (as in componentsCss.ts): selectors are
// `[data-park] .class...`, literal values, shorthands as the reference writes them. Real computed styles are
// checked again in e2e/park/worlds.spec.ts. A failing test lists every difference at once.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  declsFor,
  norm,
  parseRules,
  pick,
  readComponentsCss,
} from "../../../../test-support/park/componentsCss";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  card,
  childOf,
  leaf,
  renderWorlds,
  scaleButton,
  search,
  section,
  spotlight,
  tab,
} from "../../../../test-support/park/worldsHarness";
import * as fx from "../../api/fixtures";

afterEach(cleanup);

const pageCss = fs
  .readdirSync(__dirname)
  .filter((f) => f.endsWith(".css"))
  .map((f) => fs.readFileSync(path.join(__dirname, f), "utf8"))
  .join("\n");
const { rules } = parseRules(`${readComponentsCss()}\n${pageCss}`);

type Decls = Map<string, string>;
function declared(el: Element): Decls {
  const above = new Set<string>();
  for (let p = el.parentElement; p; p = p.parentElement)
    for (const k of Array.from(p.classList)) above.add(k);
  const d: Decls = new Map(declsFor(rules, [...el.classList], "", [...above]));
  for (const part of (el.getAttribute("style") ?? "").split(";")) {
    const i = part.indexOf(":");
    if (i > 0) d.set(part.slice(0, i).trim().toLowerCase(), part.slice(i + 1).trim());
  }
  return d;
}
/** A property as computed from `d`: padding expands to its four sides, background falls back to background-color. */
function val(d: Decls, prop: string): string {
  if (prop === "padding") {
    const p = norm(d.get("padding")).split(" ").filter(Boolean);
    const side = (s: string, i: number) =>
      p.length ? (p[i] ?? p[i - 2] ?? p[0]) : norm(d.get(`padding-${s}`));
    return ["top", "right", "bottom", "left"].map((s, i) => side(s, i)).join(" ");
  }
  if (prop === "background") return pick(d, "background", "background-color");
  if (prop === "gap") return pick(d, "gap", "column-gap", "row-gap");
  return pick(d, prop);
}
type Spec = Record<string, string | string[]>;
function checker() {
  const diffs: string[] = [];
  const check = (label: string, el: Element | null | undefined, spec: Spec) => {
    if (!el) return void diffs.push(`${label}: element not found`);
    const d = declared(el);
    for (const [prop, want] of Object.entries(spec)) {
      const ok = (Array.isArray(want) ? want : [want]).map((w) => val(new Map([[prop, w]]), prop));
      if (!ok.includes(val(d, prop)))
        diffs.push(`${label} ${prop}: got "${val(d, prop)}", want ${JSON.stringify(want)}`);
    }
  };
  return { check, diffs };
}
const NONE = ["none", ""];
const GONE = ["transparent", "none"];
const T = (size: string, weight: string, extra: Spec = {}): Spec => ({
  "font-size": size,
  "font-weight": weight,
  ...extra,
});
const CHIP: Spec = {
  height: "26px",
  padding: "0 10px",
  "border-radius": "8px",
  gap: "7px",
  ...T("12.5px", "800"),
};
const DOT: Spec = { width: "7px", height: "7px", "border-radius": "99px" };
const widthBar = (card: Element, pct: string) =>
  qa(card, "*").find((e) =>
    new RegExp(`(?:^|[;\\s])width:\\s*${pct}`).test(e.getAttribute("style") ?? ""),
  );
const A = {
  added: [
    fx.makeWorld("quick", "Compare three suppliers", 1),
    fx.makeWorld("workspace", "Plan the offsite", 2),
  ],
};

describe("WEB_5_worlds_styles: the stylesheet exists", () => {
  it("WEB_5_worlds_styles_the_page_has_its_own_stylesheet", () => {
    expect(pageCss.length).toBeGreaterThan(0);
  });
});

describe("WEB_5_worlds_styles: header, tabs, scale", () => {
  it("WEB_5_worlds_styles_header_search_and_new_world", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    check("h1", q(c, "h1"), T("36px", "900", { "letter-spacing": "-.8px", "line-height": "1.05" }));
    check("total", leaf(c, "13 worlds"), T("15px", "700", { color: "var(--ink3)" }));
    check(
      "subtitle",
      leaf(c, "Every job Tilo is running, sized by scale: cities, towns and villages."),
      T("15.5px", "600", { color: "var(--ink2)" }),
    );
    check("search box", search(c).parentElement, {
      height: "42px",
      width: "260px",
      "border-radius": "12px",
      background: "var(--field)",
      border: "1px solid var(--line)",
      padding: "0 12px",
      gap: "8px",
    });
    check("search input", search(c), T("14.5px", "600"));
    const nw = qa(c, "button").find((b) => b.textContent?.trim() === "New world");
    check("New world", nw, {
      height: "42px",
      padding: "0 18px 0 14px",
      "border-radius": "12px",
      background: "var(--hero)",
      color: "#FFFFFF",
      gap: "8px",
      ...T("15px", "800"),
    });
    expect(nw?.querySelector("svg"), "the plus icon").not.toBeNull();
    expect(diffs).toEqual([]);
  });

  it("WEB_5_worlds_styles_status_tabs_and_scale_buttons", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    const TAB: Spec = {
      height: "34px",
      padding: "0 12px",
      "border-radius": "9px",
      gap: "7px",
      ...T("14px", "700"),
    };
    check("tablist", tab(c, "All").parentElement, {
      padding: "3px",
      "border-radius": "12px",
      background: "var(--seg)",
      gap: "2px",
    });
    check("tab on", tab(c, "All"), {
      ...TAB,
      background: "var(--tabOn)",
      color: "var(--ink)",
      "box-shadow": "0 1px 3px rgba(31,29,43,.16)",
    });
    check("tab off", tab(c, "Running"), {
      ...TAB,
      background: GONE,
      color: "var(--ink2)",
      "box-shadow": NONE,
    });
    check(
      "tab count",
      tab(c, "All").querySelector("span"),
      T("12.5px", "700", { color: "var(--ink3)" }),
    );
    check(
      "SCALE",
      leaf(c, "SCALE"),
      T("12px", "800", { "letter-spacing": ".6px", color: "var(--ink3)" }),
    );
    const SC: Spec = {
      height: "34px",
      padding: "0 12px",
      "border-radius": "9px",
      ...T("13.5px", "800"),
    };
    check("scale on", scaleButton(c, "All sizes"), {
      ...SC,
      background: "var(--ink)",
      color: "var(--inv)",
    });
    check("scale off", scaleButton(c, "Cities"), {
      ...SC,
      background: "var(--chip)",
      color: "var(--ink)",
    });
    expect(diffs).toEqual([]);
  });
});

describe("WEB_5_worlds_styles: waiting for you, caught up, empty", () => {
  it("WEB_5_worlds_styles_spotlight_and_decision_cards", async () => {
    const { c } = await renderWorlds();
    const s = spotlight(c);
    const { check, diffs } = checker();
    check("spotlight", s, {
      background: "var(--amberSoft)",
      border: "1px solid var(--amberLine)",
      "border-radius": "22px",
      padding: "14px",
      gap: "14px",
    });
    check(
      "label",
      leaf(s, "WAITING FOR YOU"),
      T("12px", "800", { "letter-spacing": ".6px", color: "var(--amberInk)" }),
    );
    check("K1 title", leaf(s, "K1 electric scooter"), T("16px", "800"));
    check("paused", leaf(s, "2 buildings paused"), T("13px", "600", { color: "var(--ink2)" }));
    const title = leaf(s, "Laptop Depot · budget sign-off");
    check("decision card", title && childOf(s, title), {
      background: "var(--card)",
      "border-radius": "16px",
      padding: "14px 16px",
      gap: "12px",
    });
    check("decision title", title, T("14.5px", "800"));
    check(
      "decision body",
      leaf(s, "6 test laptops for firmware, £3,420. Above the £2,500 district limit."),
      T("13.5px", "600", { color: "var(--ink2)" }),
    );
    const BTN: Spec = {
      height: "36px",
      padding: "0 14px",
      "border-radius": "10px",
      ...T("14px", "800"),
    };
    const btn = (t: string) => qa(s, "button").find((b) => b.textContent?.trim() === t);
    check("amber button", btn("Approve £3,420"), {
      ...BTN,
      background: "#F0A500",
      color: "#1F1D2B",
    });
    check("Open in world", btn("Open in world"), {
      ...BTN,
      background: "var(--btn2)",
      border: "1px solid var(--line)",
      color: "var(--ink)",
    });
    expect(diffs).toEqual([]);
  });

  it("WEB_5_worlds_styles_all_caught_up_banner_and_empty_state", async () => {
    const { c } = await renderWorlds({ dec: { depot: true, mail: true } });
    const { check, diffs } = checker();
    const t = leaf(c, "You’re all caught up");
    check("banner", t?.parentElement?.parentElement, {
      background: "var(--okSoft)",
      "border-radius": "18px",
      padding: "10px 16px 10px 10px",
      gap: "12px",
    });
    check("banner title", t, T("15px", "800"));
    check(
      "banner body",
      leaf(c, "K1 electric scooter is moving again. Tilo will ask if anything else needs you."),
      T("13.5px", "600", { color: "var(--ink2)" }),
    );
    click(tab(c, "Needs you"));
    const e = leaf(c, "Nothing needs you right now");
    check("empty", e?.parentElement, {
      border: "1.5px dashed var(--line)",
      "border-radius": "22px",
      padding: "44px 24px",
      gap: "6px",
    });
    check("empty title", e, T("18px", "800"));
    check(
      "empty body",
      leaf(c, "Try another filter, or start something new from Home."),
      T("14px", "600", { color: "var(--ink2)" }),
    );
    expect(diffs).toEqual([]);
  });
});

describe("WEB_5_worlds_styles: sections and cards", () => {
  it("WEB_5_worlds_styles_section_headings_and_grids", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    const GRID = {
      Cities: ["330px", "18px", "4 · big projects with districts and gates", "new2"],
      Towns: ["250px", "16px", "4 · routines and small projects", "northline"],
      Villages: ["200px", "14px", "5 · quick tasks, done in minutes", "new1"],
    } as const;
    for (const [name, [min, gap, blurb, id]] of Object.entries(GRID)) {
      const sec = section(c, name);
      check(`${name} section`, sec, { gap: "14px" });
      check(`${name} title`, sec && leaf(sec, name), T("16px", "800"));
      check(`${name} count`, sec && leaf(sec, blurb), T("13.5px", "700", { color: "var(--ink3)" }));
      check(`${name} grid`, card(c, id).parentElement, {
        display: "grid",
        "grid-template-columns": `repeat(auto-fill,minmax(${min},1fr))`,
        gap,
      });
    }
    expect(diffs).toEqual([]);
  });

  it("WEB_5_worlds_styles_city_card_404", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    const k1 = card(c, "k1");
    const BASE: Spec = {
      height: "404px",
      "box-sizing": "border-box",
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "22px",
      padding: "18px 18px 16px",
      gap: "12px",
      color: "var(--ink)",
    };
    check("k1 card (needs you)", k1, {
      ...BASE,
      "box-shadow": "0 0 0 2px var(--amber), var(--sh)",
    });
    check("hires card", card(c, "hires"), { ...BASE, "box-shadow": NONE });
    check("new2 card (Starting)", card(c, "new2"), {
      ...BASE,
      "box-shadow": "0 0 0 2px var(--hero)",
    });
    check(
      "tool",
      leaf(k1, "WORKSPACE"),
      T("11.5px", "800", { "letter-spacing": ".7px", color: "var(--ink3)" }),
    );
    check(
      "name",
      leaf(k1, "K1 electric scooter"),
      T("20px", "800", { "line-height": "1.2", "letter-spacing": "-.3px" }),
    );
    check(
      "meta",
      leaf(k1, "Concept to launch · Level 3 of 6"),
      T("13.5px", "600", { color: "var(--ink2)" }),
    );
    const chip = leaf(k1, "2 decisions");
    check("needs chip", chip, { ...CHIP, background: "#F0A500", color: "#1F1D2B" });
    check("needs dot", chip?.firstElementChild, { ...DOT, background: "#1F1D2B" });
    for (const [id, word, dot, bar] of [
      ["hires", "Running", "var(--run)", "var(--run)"],
      ["audit", "Ready", "var(--ok)", "var(--ok)"],
    ]) {
      const chipEl = leaf(card(c, id as string), word as string);
      check(`${word} chip`, chipEl, { ...CHIP, background: "var(--chip)", color: "var(--ink)" });
      check(`${word} dot`, chipEl?.firstElementChild, { ...DOT, background: dot as string });
      const fill = widthBar(card(c, id as string), id === "audit" ? "100%" : "58%");
      check(`${id} bar fill`, fill, {
        height: "100%",
        "border-radius": "99px",
        background: bar as string,
      });
    }
    const art = k1.querySelector("svg");
    check("art box", art && childOf(k1, art), {
      background: "var(--sunk)",
      "border-radius": "16px",
      overflow: "hidden",
      position: "relative",
    });
    const fill = widthBar(k1, "46%");
    check("k1 bar fill", fill, {
      height: "100%",
      background: "var(--amber)",
      "border-radius": "99px",
    });
    check("bar track", fill?.parentElement, {
      height: "6px",
      "border-radius": "99px",
      background: "var(--track)",
      overflow: "hidden",
    });
    check(
      "percent",
      leaf(k1, "46%"),
      T("13px", "800", { "min-width": "36px", "text-align": "right" }),
    );
    const spend = leaf(k1, "Spend");
    check("stats grid", spend?.parentElement?.parentElement, {
      display: "grid",
      "grid-template-columns": "1.5fr 1fr 1fr",
      gap: "12px",
    });
    check("stat label", spend, T("12px", "700", { color: "var(--ink3)" }));
    check("stat value", spend?.nextElementSibling, T("14.5px", "800", { "white-space": "nowrap" }));
    check("stat of", spend?.nextElementSibling?.querySelector("span"), {
      "font-weight": "600",
      color: "var(--ink3)",
    });
    expect(diffs).toEqual([]);
  });

  it("WEB_5_worlds_styles_town_card_196", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    const n = card(c, "northline");
    check("town card", n, {
      height: "196px",
      "box-sizing": "border-box",
      position: "relative",
      overflow: "hidden",
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "20px",
      padding: "16px 16px 16px 18px",
      color: "var(--ink)",
      "box-shadow": NONE,
    });
    const chip = leaf(n, "Running");
    check("chip", chip, {
      ...CHIP,
      position: "absolute",
      top: "14px",
      right: "14px",
      background: "var(--chip)",
      color: "var(--ink)",
    });
    check("dot", chip?.firstElementChild, { ...DOT, background: "var(--run)" });
    check("scheduled dot", leaf(card(c, "invoice"), "Scheduled")?.firstElementChild, {
      ...DOT,
      background: "var(--sch)",
    });
    check(
      "tool",
      leaf(n, "WORKSPACE"),
      T("11.5px", "800", { "letter-spacing": ".7px", color: "var(--ink3)" }),
    );
    check(
      "name",
      leaf(n, "Supplier onboarding · Northline"),
      T("16px", "800", { "line-height": "1.25" }),
    );
    check(
      "meta",
      leaf(n, "Contracts and portal access"),
      T("13px", "600", { color: "var(--ink2)", "line-height": "1.35" }),
    );
    check("next", leaf(n, "Due Wed 30 Sep"), { "font-weight": "800", "font-size": "13px" });
    check("spend line", leaf(n, "£342 of £500"), { "font-weight": "600", color: "var(--ink2)" });
    const fill = widthBar(n, "72%");
    check("bar fill", fill, { height: "100%", background: "var(--run)" });
    check("bar track", fill?.parentElement, {
      position: "absolute",
      left: "0",
      right: "0",
      bottom: "0",
      height: "3px",
      background: "var(--track)",
    });
    expect(n.querySelector("svg"), "the building strip").not.toBeNull();
    expect(diffs).toEqual([]);
  });

  it("WEB_5_worlds_styles_village_card_150", async () => {
    const { c } = await renderWorlds(A);
    const { check, diffs } = checker();
    const v = card(c, "calls");
    const BASE: Spec = {
      height: "150px",
      "box-sizing": "border-box",
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "18px",
      padding: "14px 14px 14px 16px",
      gap: "8px",
      color: "var(--ink)",
    };
    check("village card", v, { ...BASE, "box-shadow": NONE });
    check("Starting card", card(c, "new1"), { ...BASE, "box-shadow": "0 0 0 2px var(--hero)" });
    const chip = leaf(v, "Running");
    check("chip", chip, { ...CHIP, background: "var(--chip)", color: "var(--ink)" });
    check("dot", chip?.firstElementChild, { ...DOT, background: "var(--run)" });
    check("done dot", leaf(card(c, "comp"), "Ready")?.firstElementChild, {
      ...DOT,
      background: "var(--ok)",
    });
    let tile = v.querySelector("svg")?.parentElement ?? null;
    while (tile && tile !== v && val(declared(tile), "width") !== "46px") tile = tile.parentElement;
    check("art tile", tile === v ? null : tile, {
      width: "46px",
      height: "46px",
      "border-radius": "12px",
      background: "var(--sunk)",
      overflow: "hidden",
    });
    check(
      "name",
      leaf(v, "Summarise yesterday’s calls"),
      T("14.5px", "800", { "line-height": "1.3" }),
    );
    check(
      "when",
      leaf(v, "About 3 min left"),
      T("12.5px", "600", {
        color: "var(--ink2)",
        "white-space": "nowrap",
        overflow: "hidden",
        "text-overflow": "ellipsis",
        "margin-top": "auto",
      }),
    );
    expect(diffs).toEqual([]);
  });
});
