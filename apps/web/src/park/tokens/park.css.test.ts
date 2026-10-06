// WEB-1a (plan section 2; README "Design tokens"): park.css is the handoff tokens.css scoped to
// [data-park]. Day values sit on [data-park], night values on [data-park][data-time="night"], same
// variable names and values as the handoff. No motion in it: the handoff's @keyframes and the
// reduced-motion block are NOT copied (BQ-WEB-3: WEB-1 to WEB-2 add no keyframes; FR-WLD-09 stays untouched).
// Defaults: the file holds no at-rules at all (it is a token file); a selector list is split on commas.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { RULES, scanSource } from "../../../test-support/honestyScan";
import { parseBlocks, propsFor, stripComments } from "../../../test-support/park/css";
import { HANDOFF_TOKENS_PATH, PARK_DIR } from "../../../test-support/park/prototype";

const PARK_CSS = path.join(PARK_DIR, "tokens", "park.css");
const DAY = "[data-park]";
const NIGHT = '[data-park][data-time="night"]';

const handoff = fs.readFileSync(HANDOFF_TOKENS_PATH, "utf8");
const handoffDay = propsFor(handoff, ":root");
const handoffNight = propsFor(handoff, '[data-time="night"]');
const park = (): string => fs.readFileSync(PARK_CSS, "utf8");

describe("WEB_1a_tokens: the reference side is real", () => {
  it("WEB_1a_tokens_handoff_tokens_parse", () => {
    expect(handoffDay.size).toBe(58);
    expect(handoffNight.size).toBe(57);
    expect(handoffDay.get("--ground")).toBe("#A6D78C");
    expect(handoffDay.get("--gFx")).toBe("blur(20px) saturate(1.5)");
    expect(handoffNight.get("--paper")).toBe("#14163A");
  });
});

describe("WEB_1a_tokens: park.css carries the handoff tokens, scoped", () => {
  it("WEB_1a_tokens_park_css_exists", () => {
    expect(fs.existsSync(PARK_CSS), `${PARK_CSS} must exist`).toBe(true);
  });

  it("WEB_1a_tokens_day_values_on_data_park", () => {
    const day = propsFor(park(), DAY);
    for (const [name, value] of handoffDay) {
      expect(day.get(name), `${name} under ${DAY}`).toBe(value);
    }
    // No custom property that the handoff does not have (names and values stay the design's).
    expect([...day.keys()].sort()).toEqual([...handoffDay.keys()].sort());
  });

  it("WEB_1a_tokens_night_values_on_data_park_data_time_night", () => {
    const night = propsFor(park(), NIGHT);
    for (const [name, value] of handoffNight) {
      expect(night.get(name), `${name} under ${NIGHT}`).toBe(value);
    }
    expect([...night.keys()].sort()).toEqual([...handoffNight.keys()].sort());
  });

  it("WEB_1a_tokens_night_does_not_redefine_day_only_tokens", () => {
    // e.g. --amber has no night value in the design: it stays the day colour in both themes.
    const night = propsFor(park(), NIGHT);
    for (const name of handoffDay.keys()) {
      if (!handoffNight.has(name))
        expect(night.has(name), `${name} must not be set at night`).toBe(false);
    }
    expect(night.has("--amber")).toBe(false);
  });

  it("WEB_1a_tokens_every_selector_starts_with_data_park", () => {
    const blocks = parseBlocks(park());
    expect(blocks.length).toBeGreaterThanOrEqual(2);
    for (const b of blocks) {
      expect(b.atRule, `no at-rules in the token file, found ${b.selector}`).toBe(false);
      for (const sel of b.selector.split(",")) {
        expect(sel.startsWith("[data-park]"), `selector "${sel}" must start with [data-park]`).toBe(
          true,
        );
      }
    }
    const selectors = blocks.map((b) => b.selector);
    expect(selectors).toContain(DAY);
    expect(selectors).toContain(NIGHT);
    // Never the bare global scopes of the handoff file.
    expect(selectors).not.toContain(":root");
    expect(selectors).not.toContain('[data-time="night"]');
  });
});

describe("WEB_1a_tokens: park.css has no motion (FR-WLD-09, HR-1..HR-3)", () => {
  it("WEB_1a_tokens_no_keyframes_animation_or_transition", () => {
    const css = stripComments(park());
    expect(css).not.toMatch(/@keyframes/i);
    expect(css).not.toMatch(/animation/i);
    expect(css).not.toMatch(/transition/i);
    expect(css).not.toMatch(/prefers-reduced-motion/i);
    expect(css).not.toMatch(/scroll-behavior/i);
  });

  it("WEB_1a_tokens_the_honesty_scanner_finds_nothing_in_park_css", () => {
    expect(scanSource("src/park/tokens/park.css", park())).toEqual([]);
    expect(RULES.length).toBeGreaterThan(5);
  });

  it("WEB_1a_tokens_the_handoff_motion_block_is_what_must_not_be_copied", () => {
    // Guard on the reference: the handoff does carry keyframes, so "none in park.css" is a real choice.
    expect(handoff).toMatch(/@keyframes tiloSpin/);
  });
});
