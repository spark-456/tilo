/**
 * P0-08b camera C11. qa-breaker found (P0-08a, .claude/agent-memory/qa-breaker/
 * web-stage-attack-patterns.md, note under #6) that the stage frame's focus ring was the
 * browser's default 1px `outline`, drawn *outside* the element's box: because the stage frame's
 * top and bottom edges sit flush with the viewport, that outline was clipped there and only the
 * thin left/right side lines were ever visible — a keyboard user tabbing to the world stage
 * (PRD 9.7 "keyboard pan and zoom"; FR-WLD-11 "keyboard world outline") got no visible focus
 * indicator on two of its four sides. An inset indicator (outline-offset <= 0, or an equivalent
 * inset box-shadow) can never be clipped this way, regardless of where the frame sits.
 *
 * Public interface: none beyond `[data-testid="stage-frame"]` (existing, P0-08a).
 */
import { type Page, expect, test } from "@playwright/test";
import { requireBox } from "./support/assertions";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

test("P0-08b camera C11 PRD-9.7/FR-WLD-11 keyboard focus: the stage frame's focus indicator is inset, so it can't be clipped by the viewport", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const style = await stage.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      outlineStyle: s.outlineStyle,
      outlineWidth: s.outlineWidth,
      outlineOffset: s.outlineOffset,
    };
  });
  expect(style.outlineStyle, "no focus indicator at all").not.toBe("none");
  expect(Number.parseFloat(style.outlineWidth)).toBeGreaterThan(0);
  expect(
    Number.parseFloat(style.outlineOffset),
    "outline-offset 0 (the browser default) still draws the outline starting at the box edge and " +
      "extending outward — exactly what got clipped in P0-08a. Only a negative (inset) offset can't be.",
  ).toBeLessThan(0);
});

test("P0-08b camera C11 PRD-9.7/FR-WLD-11 keyboard focus: the indicator is visible at the stage frame's very top and bottom rows, not just its sides", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  const box = requireBox(await stage.boundingBox(), "stage-frame");

  const rowChanged = async (y: number): Promise<boolean> => {
    await stage.evaluate((el) => (el as HTMLElement).blur());
    const before = await page.screenshot({ clip: { x: box.x, y, width: box.width, height: 1 } });
    await stage.focus();
    const after = await page.screenshot({ clip: { x: box.x, y, width: box.width, height: 1 } });
    return !before.equals(after);
  };

  expect(
    await rowChanged(Math.round(box.y) + 1),
    "the top row did not change when focused — the outline is clipped there",
  ).toBe(true);
  expect(
    await rowChanged(Math.round(box.y + box.height) - 2),
    "the bottom row did not change when focused — the outline is clipped there",
  ).toBe(true);
});
