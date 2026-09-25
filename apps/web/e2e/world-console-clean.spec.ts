import { expect, test } from "@playwright/test";
import { PAN_STEP_PX } from "../src/stage/camera";
import { DESKTOP, MOBILE } from "./support/viewports";
import { fixtureUrl, stageCanvas, stageFrame } from "./support/world";

// P10: "Zero console errors or warnings in fixture mode at every viewport; the camera keeps
// working with the world on screen." Same console-capture pattern as
// apps/web/e2e/console-errors.spec.ts, run in fixture mode instead of the empty stage.

const STAGE = { width: 1920, height: 1080 } as const;
const SIZES = {
  desktop: { viewport: DESKTOP, extra: {} },
  mobile: { viewport: MOBILE, extra: {} },
  stage: { viewport: STAGE, extra: { display: "stage" } },
} as const;

for (const [name, { viewport, extra }] of Object.entries(SIZES)) {
  test.describe(`${name} fixture-mode console`, () => {
    test.use({ viewport });

    test(`P10 fixture mode: zero console errors or warnings at ${name} size`, async ({ page }) => {
      const messages: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error" || msg.type() === "warning") {
          messages.push(`[${msg.type()}] ${msg.text()}`);
        }
      });
      page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));

      await page.goto(fixtureUrl("village-basic", { seq: 20, ...extra }));
      await expect(stageCanvas(page)).toBeVisible();
      await page.waitForTimeout(500);

      expect(messages, messages.join("\n")).toEqual([]);
    });
  });
}

test.use({ viewport: DESKTOP });

test("P10 fixture mode: the camera still pans with the world on screen (keyboard arrow keys)", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { seq: 20 }));
  const frame = stageFrame(page);
  await expect(stageCanvas(page)).toBeVisible();
  await frame.focus();

  const before = await frame.getAttribute("data-camera-x");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(400); // > the 320ms camera pan duration

  await expect.poll(async () => frame.getAttribute("data-camera-x")).not.toBe(before);
  const after = Number(await frame.getAttribute("data-camera-x"));
  const beforeNum = Number(before ?? "0");
  expect(after - beforeNum, "ArrowRight should pan by -PAN_STEP_PX while the world is loaded").toBe(
    -PAN_STEP_PX,
  );
});
