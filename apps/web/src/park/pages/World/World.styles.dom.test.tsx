// @vitest-environment happy-dom
// WEB-6 style spec on the rendered page: the declarations that apply to the controls the reference styles
// inline, whichever stylesheet they come from (the core Button stylesheet or World.css; read the way
// test-support/park/pageCss.ts reads them: simple class selectors, descendant combinators, literal values,
// later rule wins). Pinned values are the reference's (Tilo App World.dc.html): header buttons h42 r12 14.5/800
// (`0 16px 0 14px`), "Open live view" h42 `0 18px` --hero #FFFFFF, Approve h34 `0 14px` #F0A500 on #1F1D2B
// 13.5/800, Ask me later h34 `0 12px`, Run now / Open result h38 r11 14/800 --hero, See in Agenda / Share to
// Slack h38 `0 14px` r11, the sheet `24px 32px 36px` gap 22 r28, the h1 36px Nunito 900.
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { norm } from "../../../../test-support/park/componentsCss";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { q } from "../../../../test-support/park/componentsHarness";
import { type Decls, declared, rulesOf } from "../../../../test-support/park/pageCss";
import { control, controls, mountWorld, textOf } from "../../../../test-support/park/worldHarness";

afterEach(cleanup);

const RULES = () => rulesOf(join(__dirname, "World.css"));

/** CSS `padding` shorthand with longhand overrides, as [top, right, bottom, left]. */
function padding(d: Decls): [number, number, number, number] {
  const n = (d.get("padding") ?? "0").match(/-?\d*\.?\d+/g)?.map(Number) ?? [0];
  const [a = 0, b = a, c = a, e = b] = n;
  const box: [number, number, number, number] = [a, b, c, e];
  const longhand = ["padding-top", "padding-right", "padding-bottom", "padding-left"] as const;
  longhand.forEach((k, i) => {
    const v = d.get(k);
    if (v !== undefined) box[i] = Number.parseFloat(v);
  });
  return box;
}
const bg = (d: Decls) => norm(d.get("background") ?? d.get("background-color"));
const px = (d: Decls, k: string) => Number.parseFloat(d.get(k) ?? "NaN");

interface Look {
  height: number;
  pad: [number, number, number, number];
  radius: number;
  font: number;
  weight: string;
  bg: string;
  color: string;
  border?: string;
  gap?: number;
}
const LOOK = {
  secondary: {
    weight: "800",
    bg: "var(--btn2)",
    color: "var(--ink)",
    border: "1px solid var(--line)",
  },
  hero: { weight: "800", bg: "var(--herofill)", color: "#ffffff" }, // BQ-DS-A11Y-1: heroFill, lower-cased by the computed style
} as const;

function check(label: string, el: Element, want: Look): void {
  const d = declared(el, RULES());
  expect(px(d, "height"), `${label} height`).toBe(want.height);
  expect(padding(d), `${label} padding`).toEqual(want.pad);
  expect(px(d, "border-radius"), `${label} radius`).toBe(want.radius);
  expect(px(d, "font-size"), `${label} font-size`).toBe(want.font);
  expect(norm(d.get("font-weight")), `${label} weight`).toBe(want.weight);
  expect(bg(d), `${label} background`).toBe(want.bg);
  expect(norm(d.get("color")), `${label} colour`).toBe(want.color);
  if (want.border) expect(norm(d.get("border")), `${label} border`).toBe(want.border);
  if (want.gap !== undefined) expect(px(d, "gap"), `${label} gap`).toBe(want.gap);
}

describe("WEB_6_world_styles_dom: the sheet and the title", () => {
  it("WEB_6_world_styles_dom_the_sheet_is_24_32_36_gap_22_r28_with_the_page_border", async () => {
    const { el } = await mountWorld();
    const d = declared(q(el, "section.park-sheet"), RULES());
    expect(padding(d)).toEqual([24, 32, 36, 32]);
    expect(px(d, "gap")).toBe(22);
    expect(px(d, "border-radius")).toBe(28);
    expect(norm(d.get("border"))).toBe("1px solid var(--gbd)");
  });

  // STUDIO-3: the Studio h1 ("Tilo S World": 34px 700, tracking -0.6, line 1.15; the family is the theme's Geist).
  it("STUDIO_3_world_styles_dom_the_h1_is_700_34px_tracking_minus_0_6_line_1_15", async () => {
    const { el } = await mountWorld();
    const d = declared(q(el, "h1"), RULES());
    expect(px(d, "font-size")).toBe(34);
    expect(norm(d.get("font-weight"))).toBe("700");
    expect(norm(d.get("letter-spacing"))).toBe("-.6px");
    expect(norm(d.get("line-height"))).toBe("1.15");
    expect(norm(d.get("margin"))).toBe("0");
  });
});

describe("WEB_6_world_styles_dom: the buttons", () => {
  it("WEB_6_world_styles_dom_Pause_is_h42_r12_secondary", async () => {
    const { el } = await mountWorld();
    const want: Look = {
      height: 42,
      pad: [0, 16, 0, 14],
      radius: 12,
      font: 14.5,
      ...LOOK.secondary,
      gap: 8,
    };
    check("Pause", control(el, "Pause"), want);
  });

  // STUDIO-3: the header holds one quiet outlined control per action ("Tilo S World" secBtn: h44 r14 15/800).
  it("STUDIO_3_world_styles_dom_Open_live_view_is_h44_0_18_outlined_on_card", async () => {
    const { el } = await mountWorld();
    check("Open live view", control(el, "Open live view"), {
      height: 44,
      pad: [0, 18, 0, 18],
      radius: 14,
      font: 15,
      weight: "800",
      bg: "var(--card)",
      color: "var(--ink)",
      border: "1px solid var(--linestrong)",
      gap: 8,
    });
  });

  it("WEB_6_world_styles_dom_Approve_is_h34_0_14_amber_on_ink_and_Ask_me_later_h34_0_12_secondary", async () => {
    const { el } = await mountWorld();
    check("Approve", control(el, "Approve £3,420"), {
      height: 34,
      pad: [0, 14, 0, 14],
      radius: 10,
      font: 13.5,
      weight: "800",
      bg: "#f0a500",
      color: "#1f1d2b",
    });
    const later = controls(el).find((e) => textOf(e) === "Ask me later");
    check("Ask me later", later as Element, {
      height: 34,
      pad: [0, 12, 0, 12],
      radius: 10,
      font: 13.5,
      ...LOOK.secondary,
    });
  });

  it("WEB_6_world_styles_dom_Run_now_is_h38_0_14_0_12_hero_and_See_in_Agenda_h38_0_14_secondary", async () => {
    const { el } = await mountWorld({ id: "invoice" });
    check("Run now", control(el, "Run now"), {
      height: 38,
      pad: [0, 14, 0, 12],
      radius: 11,
      font: 14,
      ...LOOK.hero,
      gap: 7,
    });
    check("See in Agenda", control(el, "See in Agenda"), {
      height: 38,
      pad: [0, 14, 0, 14],
      radius: 11,
      font: 14,
      ...LOOK.secondary,
    });
  });

  it("WEB_6_world_styles_dom_Open_result_is_h38_0_16_hero_and_Share_to_Slack_h38_0_14_secondary", async () => {
    const { el } = await mountWorld({ id: "comp" });
    check("Open result", control(el, "Open result"), {
      height: 38,
      pad: [0, 16, 0, 16],
      radius: 11,
      font: 14,
      ...LOOK.hero,
    });
    check("Share to Slack", control(el, "Share to Slack"), {
      height: 38,
      pad: [0, 14, 0, 14],
      radius: 11,
      font: 14,
      ...LOOK.secondary,
    });
  });
});
