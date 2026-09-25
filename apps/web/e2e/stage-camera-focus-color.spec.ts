/**
 * P0-08b camera C11, colour half (the clipping half is in stage-camera-a11y.spec.ts): the
 * stage frame's focus indicator must "use the focus colour token from design/tokens.json
 * (see apps/web/src/design/tokens.ts)".
 *
 * Ambiguity (ticket brief: "pick its stated default, note it in a comment with the PRD
 * section, and list it in your report"): neither PRD 18.2's colour-role table nor
 * design/tokens.json defines a dedicated "focus" role — only brand, surface, district, signal,
 * ink, fog and policy roles exist (see design/tokens.json's `color` object; confirmed no
 * "focus" key anywhere in it or in apps/web/src/design/tokens.ts). Per this repo's ambiguity
 * rule (root CLAUDE.md 3 "apply the PRD's stated default... never invent requirements"), this
 * test uses `tokens.color.brand.primary` (`--color-brand-primary`, #5A3FE0): PRD 18.2's colour
 * table lists brand.primary first and it is already the app's one interactive/selected-state
 * colour (e.g. the nav button's text), so it is the PRD's own nearest stated default rather
 * than an invented colour. Flagged for the user/design-critic to confirm or override.
 *
 * Public interface: none beyond `[data-testid="stage-frame"]` (existing, P0-08a) and
 * apps/web/src/design/tokens.ts's `tokens.color.brand.primary` (existing).
 */
import { expect, test } from "@playwright/test";
import tokens from "../src/design/tokens";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

function hexToRgb(hex: string): string {
  const n = Number.parseInt(hex.replace("#", ""), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

test("P0-08b camera C11 PRD-17.5/18.2: the focused stage frame's outline colour is the focus token (tokens.color.brand.primary)", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const outlineColor = await stage.evaluate((el) => getComputedStyle(el).outlineColor);
  expect(outlineColor).toBe(hexToRgb(tokens.color.brand.primary));
});
