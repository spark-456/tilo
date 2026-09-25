import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const CORNERS = ["tl", "tr", "bl", "br"] as const;
type Corner = (typeof CORNERS)[number];

/** Draws the stage canvas onto an offscreen 2D canvas and reports whether a
 * `size`px-square sample at `corner` (in CSS pixels) contains any pixel that
 * differs from the sample's own first pixel — i.e. whether the solid
 * background there is broken up by grid ink. Runs entirely in the page so it
 * works regardless of the source canvas's WebGL buffer-preservation. */
async function cornerHasGridInk(
  canvas: ReturnType<import("@playwright/test").Page["locator"]>,
  corner: Corner,
  size = 20,
): Promise<boolean> {
  return canvas.evaluate(
    (el: HTMLCanvasElement, args: { corner: Corner; size: number }) => {
      const off = document.createElement("canvas");
      off.width = el.width;
      off.height = el.height;
      const ctx = off.getContext("2d");
      if (!ctx) return false;
      ctx.drawImage(el, 0, 0);

      const scaleX = el.width / el.clientWidth;
      const scaleY = el.height / el.clientHeight;
      const w = Math.round(args.size * scaleX);
      const h = Math.round(args.size * scaleY);
      const x = args.corner === "tl" || args.corner === "bl" ? 0 : el.width - w;
      const y = args.corner === "tl" || args.corner === "tr" ? 0 : el.height - h;

      const { data } = ctx.getImageData(x, y, w, h);
      const [r0, g0, b0] = [data[0], data[1], data[2]];
      for (let i = 4; i < data.length; i += 4) {
        if (data[i] !== r0 || data[i + 1] !== g0 || data[i + 2] !== b0) return true;
      }
      return false;
    },
    { corner, size },
  );
}

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`${name} grid coverage`, () => {
    test.use({ viewport });

    test(`PRD-9.7 stage grid: the iso grid reaches every corner of the stage at ${name} size`, async ({
      page,
    }) => {
      await page.goto("/");
      const canvas = page.getByTestId("stage-frame").locator("canvas");
      await expect(canvas).toBeVisible();
      await page.waitForTimeout(300); // let the initial resize/draw settle

      for (const corner of CORNERS) {
        expect(
          await cornerHasGridInk(canvas, corner),
          `${corner} corner of the ${name} stage has no grid ink — the diamond is clipped`,
        ).toBe(true);
      }
    });
  });
}
