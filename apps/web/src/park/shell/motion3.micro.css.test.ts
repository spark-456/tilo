// WEB-MOTION-3 (FR-UX-12): micro-interactions of the Park handoff, read from the shell stylesheet as text.
// Reference: design_handoff_tilo_web_app/README.md "Interactions and motion" and the inline styles of
// design_handoff_tilo_web_app/design/Tilo App *.dc.html (hover lifts .3s cubic-bezier(.2,.8,.2,1), the sliding
// thumb .4s cubic-bezier(.34,1.3,.5,1), the switch knob .25s cubic-bezier(.3,1.3,.5,1), the pin spring .45s).
// Hard limits from the earlier tickets (kept, not loosened): only park.shell.css may transition; only transform
// and opacity; no backdrop-filter on anything that moves; no new keyframes; reduced motion and 'still' turn it off.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST } from "../../../test-support/honestyScan";
import { type CssRule, parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const read = (file: string): string => fs.readFileSync(path.join(__dirname, file), "utf8");
const shell = (): string => read("park.shell.css");
const MAIN = "[data-park] .park-shell__main";

const rule = (rules: readonly CssRule[], selector: string): CssRule | undefined =>
  rules.find((r) => r.selector === selector);
const bezier = (a: string, b: string, c: string, d: string): RegExp =>
  new RegExp(`cubic-bezier\\(\\s*${a}\\s*,\\s*${b}\\s*,\\s*${c}\\s*,\\s*${d}\\s*\\)`);
const norm = (v: string | undefined): string => (v ?? "").replace(/(^|[^\d])0\./g, "$1.");

/** [selector, transition regex]: the base state carries the transition, so both directions move. */
const TRANSITIONS: readonly [string, RegExp][] = [
  // Hover lifts (README cards/tiles; Tilo App Worlds/Home/Connectors: transform .3s cubic-bezier(.2,.8,.2,1)).
  [`${MAIN} .park-worlds-card`, /transform \.3s cubic-bezier\(\.2, \.8, \.2, 1\)/],
  [`${MAIN} .park-home-pin__card`, /transform \.3s cubic-bezier\(\.2, \.8, \.2, 1\)/],
  [`${MAIN} .park-connectors-tile`, /transform \.3s cubic-bezier\(\.2, \.8, \.2, 1\)/],
  // The pinboard note straightens and lifts with a spring (Tilo App Agenda: transform .45s (.34,1.4,.5,1)).
  [`${MAIN} .park-agenda-pin`, /transform \.45s cubic-bezier\(\.34, 1\.4, \.5, 1\)/],
  [`${MAIN} .park-agenda-event`, /transform \.2s/],
  // Press (Home start: transform .15s) and the shared button.
  [`${MAIN} .park-home-start`, /transform \.15s/],
  [`${MAIN} .park-btn`, /transform \.15s/],
  // The sliding thumb and the switch knobs.
  [
    `${MAIN} .park-seg--sliding .park-seg__thumb`,
    /transform \.4s cubic-bezier\(\.34, 1\.3, \.5, 1\)/,
  ],
  [`${MAIN} .park-switch__knob`, /transform \.25s cubic-bezier\(\.3, 1\.3, \.5, 1\)/],
  [`${MAIN} .park-profile-knob`, /transform \.25s cubic-bezier\(\.3, 1\.3, \.5, 1\)/],
  [`${MAIN} .park-skills-ask-knob`, /transform \.25s cubic-bezier\(\.3, 1\.3, \.5, 1\)/],
  [`${MAIN} .park-agenda-knob`, /transform \.25s cubic-bezier\(\.3, 1\.3, \.5, 1\)/],
];

describe("WEB-MOTION-3 css: hover, press and slide feedback is a transform transition in the shell stylesheet", () => {
  for (const [selector, re] of TRANSITIONS) {
    it(`FR_UX_12 WEB-MOTION-3 css: ${selector.replace(`${MAIN} `, "")} has the handoff's transition`, () => {
      const r = rule(parseRules(shell()).rules, selector);
      expect(r, `park.shell.css has no rule ${selector}`).toBeDefined();
      expect(norm(r?.decls.get("transition"))).toMatch(re);
    });
  }

  it("FR_UX_12 WEB-MOTION-3 css: Worlds cards lift 3px and Connectors tiles 2px on hover (Tilo App Worlds, Connectors style-hover)", () => {
    const rules = parseRules(shell()).rules;
    expect(rule(rules, `${MAIN} .park-worlds-card:hover`)?.decls.get("transform")).toBe(
      "translateY(-3px)",
    );
    expect(rule(rules, `${MAIN} .park-connectors-tile:hover`)?.decls.get("transform")).toBe(
      "translateY(-2px)",
    );
  });

  it("FR_UX_12 WEB-MOTION-3 css: a pressed button moves 1px, a pressed Home start keeps its own 2px", () => {
    const rules = parseRules(shell()).rules;
    const press = rules.find(
      (r) => r.selector.startsWith(`${MAIN} .park-btn:active`) && r.decls.has("transform"),
    );
    expect(press?.decls.get("transform")).toBe("translateY(1px)");
  });

  it("FR_UX_12 WEB-MOTION-3 css: the nav's hover fade is an opacity overlay (a background colour never transitions)", () => {
    const rules = parseRules(shell()).rules;
    for (const cls of ["park-shell__tab", "park-shell__iconbtn", "park-shell__nrow"]) {
      const over = rule(rules, `[data-park] .${cls}::before`);
      expect(over, `${cls}::before`).toBeDefined();
      expect(over?.decls.get("opacity")).toBe("0");
      expect(norm(over?.decls.get("transition"))).toMatch(/^opacity \.2s/);
      const on = rules.find(
        (r) => r.selector === `[data-park] .${cls}:hover::before` && r.decls.get("opacity") === "1",
      );
      expect(on, `${cls}:hover::before shows the overlay`).toBeDefined();
    }
  });

  it("FR_UX_12 WEB-MOTION-3 css: no page ring turns (the Home draft and the Connectors connect are stand-ins with no call behind them, HR-1)", () => {
    const rules = parseRules(shell()).rules;
    expect(rule(rules, `${MAIN} .park-shell__ring--page`)).toBeUndefined();
    expect(
      rules.filter(
        (r) => r.selector.includes(MAIN) && !/^none/.test(r.decls.get("animation") ?? "none"),
      ),
    ).toEqual([]);
  });

  it("FR_UX_12 WEB-MOTION-3 css: toast, popover and menu come in with an opacity and transform transition from a pre state", () => {
    const rules = parseRules(shell()).rules;
    expect(rule(rules, "[data-park] .park-shell__enter")?.decls.get("display")).toBe("contents");
    const toast = rule(rules, "[data-park] .park-shell__enter > .park-toast");
    const pop = rule(rules, "[data-park] .park-shell__enter > .park-popover");
    for (const r of [toast, pop]) {
      expect(norm(r?.decls.get("transition"))).toMatch(/opacity \.\d+s/);
      expect(norm(r?.decls.get("transition"))).toMatch(/transform \.\d+s/);
    }
    const preToast = rule(rules, '[data-park] .park-shell__enter[data-enter="pre"] > .park-toast');
    const prePop = rule(rules, '[data-park] .park-shell__enter[data-enter="pre"] > .park-popover');
    expect(preToast?.decls.get("opacity")).toBe("0");
    expect(prePop?.decls.get("opacity")).toBe("0");
    // The toast is centred with translateX(-50%): the pre state keeps it centred.
    expect(preToast?.decls.get("transform")).toMatch(/translateX\(-50%\)/);
  });
});

describe("WEB-MOTION-3 css: the limits of the earlier tickets still hold", () => {
  it("FR_UX_12 WEB-MOTION-3 css: no new @keyframes and no @starting-style (the shell's list is pinned in shell.css.test.ts)", () => {
    const heads = parseRules(shell()).others.map((o) => o.head);
    expect(heads.filter((h) => /starting-style|view-transition/.test(h))).toEqual([]);
    expect(heads).toEqual([
      "@keyframes mvXY",
      "@keyframes waddle",
      "@keyframes walkFrame",
      "@keyframes tiloSlide",
      "@keyframes tiloSpin",
      "@keyframes tiloFade",
    ]);
  });

  it("FR_UX_12 WEB-MOTION-3 css: every rule that starts motion sits under a park-shell__ class (page controls under the page outlet)", () => {
    const moves = (v: string | undefined): boolean => v !== undefined && !v.startsWith("none");
    for (const r of parseRules(shell()).rules) {
      if (!(moves(r.decls.get("transition")) || moves(r.decls.get("animation")))) continue;
      expect(r.selector).toMatch(/^\[data-park\][^,]*\.park-shell__/);
    }
  });

  it("FR_UX_12 WEB-MOTION-3 css: nothing that moves carries a backdrop-filter, a will-change or a layout property in its transition", () => {
    const blurred = new Set(
      parseRules(shell())
        .rules.filter((r) => r.decls.has("backdrop-filter"))
        .map((r) => r.selector),
    );
    for (const r of parseRules(shell()).rules) {
      const t = r.decls.get("transition");
      if (t === undefined || t.startsWith("none")) continue;
      expect(blurred.has(r.selector), `${r.selector} blurs and moves`).toBe(false);
      expect(r.decls.has("will-change"), `${r.selector} will-change`).toBe(false);
      expect(t).not.toMatch(
        /\b(?:width|height|top|left|right|bottom|margin|padding|box-shadow|filter|all)\b/,
      );
    }
    // The Home glass chip blurs: its lift is not built (it would move a backdrop-filter layer).
    const text = stripComments(shell());
    expect(text).not.toMatch(/park-home-chip/);
  });

  it("FR_UX_12 WEB-MOTION-3 css: the honesty allowlist gains no entry", () => {
    expect(ALLOWLIST.map((a) => `${a.file}:${a.rule}`).sort()).toEqual(
      [
        "src/world/runWorld.ts:raf",
        "src/stage/Stage.tsx:raf",
        "src/park/engines/park.ts:inline-motion-style",
        "src/park/engines/park.ts:css-animation",
        "src/park/shell/park.shell.css:css-keyframes",
        "src/park/shell/park.shell.css:css-animation",
        "src/park/shell/park.shell.css:css-transition",
      ].sort(),
    );
  });

  it("FR_UX_12 WEB-MOTION-3 css: page and component stylesheets still hold no transition, animation or keyframes", () => {
    const park = path.join(__dirname, "..");
    const files = [path.join(park, "components", "park.components.css")];
    for (const dir of fs.readdirSync(path.join(park, "pages"))) {
      const d = path.join(park, "pages", dir);
      for (const f of fs.readdirSync(d)) if (f.endsWith(".css")) files.push(path.join(d, f));
    }
    for (const f of files) {
      const body = stripComments(fs.readFileSync(f, "utf8"));
      expect(body, f).not.toMatch(
        /(?:^|[\s{;])(?:transition|animation)(?:-[a-z-]+)?\s*:|@keyframes/,
      );
    }
  });
});

describe("WEB-MOTION-3 css: reduced motion and the 'still' preference turn every transition and animation off", () => {
  /** The `none` rules: media-query rules are flattened by the reader, so find them by their declarations. */
  const offRules = (): CssRule[] =>
    parseRules(shell()).rules.filter(
      (r) =>
        /^none\b/.test(r.decls.get("transition") ?? "") ||
        /^none\b/.test(r.decls.get("animation") ?? ""),
    );

  it("FR_UX_12 WEB-MOTION-3 css: the reduced-motion block (inside @media (prefers-reduced-motion: reduce)) covers the page outlet's descendants, the nav pieces, the popovers and the toast", () => {
    const text = stripComments(shell());
    const m = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/.exec(text);
    expect(m, "the file ends with the reduced-motion block").not.toBeNull();
    const block = m?.[1] ?? "";
    expect(block).toMatch(/\.park-shell__main \*/);
    expect(block).toMatch(/park-shell__tab::before/);
    expect(block).toMatch(/park-shell__iconbtn::before/);
    expect(block).toMatch(/park-shell__nrow::before/);
    expect(block).toMatch(/park-shell__enter > \.park-toast/);
    expect(block).toMatch(/park-shell__enter > \.park-popover/);
    expect(block).toMatch(/transition:\s*none\s*!important/);
    expect(block).toMatch(/animation:\s*none\s*!important/);
  });

  it("FR_UX_12 WEB-MOTION-3 css: the still preference (data-motion on the root) has the same list, rule for rule", () => {
    const still = offRules().filter((r) =>
      r.selector.startsWith('[data-park][data-motion="still"]'),
    );
    const stillTails = new Set(
      still.map((r) => r.selector.replace('[data-park][data-motion="still"]', "").trim()),
    );
    const reduce = offRules().filter((r) => !r.selector.includes("data-motion"));
    const reduceTails = new Set(reduce.map((r) => r.selector.replace("[data-park]", "").trim()));
    for (const tail of [
      ".park-shell__main *",
      ".park-shell__tab::before",
      ".park-shell__iconbtn::before",
      ".park-shell__nrow::before",
      ".park-shell__enter > .park-toast",
      ".park-shell__enter > .park-popover",
    ]) {
      expect(reduceTails.has(tail), `reduced motion: ${tail}`).toBe(true);
      expect(stillTails.has(tail), `still: ${tail}`).toBe(true);
    }
  });
});
