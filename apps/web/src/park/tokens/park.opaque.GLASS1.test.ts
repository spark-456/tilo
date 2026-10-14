// GLASS-1: nothing that carries text lets what is behind it show through. The surface tokens are solid colours, the
// glass blur is off, and the sign-in card is solid. Overlays that carry no text (--veil, --scrim) may stay translucent.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(join(__dirname, "..", "..", rel), "utf8");
const SOLID = /^#[0-9a-fA-F]{6}$/;
const SURFACES = ["--gBg", "--sheet"] as const;
const NIGHT_SURFACES = ["--card", "--field", "--tabOn"] as const;

function block(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("\n}", start));
}
const value = (decls: string, name: string): string => {
  const m = new RegExp(`${name}:\s*([^;]+);`).exec(decls);
  expect(m, name).not.toBeNull();
  return (m?.[1] ?? "").trim();
};

// park.css is the handoff and stays so; park.opaque.css overrides what carried text. Every importer of the one loads
// the other straight after it, so the override wins on equal specificity.
describe("GLASS_1_tokens: the Park surface tokens are opaque", () => {
  const css = read("park/tokens/park.opaque.css");
  for (const [mode, selector] of [
    ["day", "[data-park]"],
    ["night", '[data-park][data-time="night"]'],
  ] as const) {
    const decls = block(css, selector);
    for (const token of mode === "night" ? [...SURFACES, ...NIGHT_SURFACES] : SURFACES) {
      it(`GLASS_1_${mode}_${token}_is_a_solid_colour`, () => {
        expect(value(decls, token)).toMatch(SOLID);
      });
    }
    it(`GLASS_1_${mode}_the_glass_blur_is_off`, () => {
      expect(value(decls, "--gFx")).toBe("none");
    });
  }
});

describe("GLASS_1_signin: the sign-in card is opaque", () => {
  const css = read("auth/signin.css");
  it("GLASS_1_signin_card_tokens_are_solid_and_nothing_blurs", () => {
    for (const m of css.matchAll(/--si-card:\s*([^;]+);/g))
      expect((m[1] ?? "").trim()).toMatch(SOLID);
    expect(css).not.toMatch(/backdrop-filter\s*:\s*blur/);
  });
});

describe("GLASS_1_import: the override loads wherever the handoff tokens do", () => {
  it("GLASS_1_import_every_park_css_importer_loads_park_opaque_css_after_it", () => {
    const files = [
      "access/AccessScreen.tsx",
      "auth/SignInBackdrop.tsx",
      "legal/LegalPage.tsx",
      "oauth/CallbackPage.tsx",
      "park/app/ParkApp.tsx",
      "park/dev/Components.tsx",
      "park/shell/SettingsAppearance.tsx",
    ];
    for (const f of files) {
      const src = read(f);
      const at = src.indexOf("tokens/park.css");
      expect(at, f).toBeGreaterThanOrEqual(0);
      expect(src.indexOf("tokens/park.opaque.css"), f).toBeGreaterThan(at);
    }
  });
});
