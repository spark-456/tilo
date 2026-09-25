import { type Page, expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

const measure = (page: Page) =>
  page.evaluate(() => {
    const px = (sel: string, prop: "fontSize" | "minHeight") => {
      const el = document.querySelector(sel);
      if (!el) throw new Error(`${sel} missing`);
      return Number.parseFloat(getComputedStyle(el)[prop]);
    };
    return {
      mode: document.querySelector<HTMLElement>(".app-shell")?.dataset.stageMode,
      heading: px(".right-rail h2", "fontSize"),
      body: px(".right-rail .empty", "fontSize"),
      target: px(".nav-btn", "minHeight"),
      structure: [...document.querySelectorAll("[data-testid]")]
        .map((e) => (e as HTMLElement).dataset.testid)
        .join(","),
    };
  });

test("PRD-18.2 stage mode: the display setting scales type and targets by 1.25 without a separate code path", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("right-rail")).toBeVisible();
  const normal = await measure(page);
  expect(normal.mode).toBe("off");

  // Flipping the one attribute on the same, already-rendered shell is the whole switch.
  await page.evaluate(() => {
    document.querySelector<HTMLElement>(".app-shell")?.setAttribute("data-stage-mode", "on");
  });
  const flipped = await measure(page);
  for (const key of ["heading", "body", "target"] as const) {
    expect(flipped[key] / normal[key], `${key} did not scale by 1.25`).toBeCloseTo(1.25, 2);
  }
  expect(flipped.structure).toBe(normal.structure);

  // Opening the app with the setting gives the same result as flipping it.
  await page.goto("/?display=stage");
  await expect(page.getByTestId("right-rail")).toBeVisible();
  const opened = await measure(page);
  expect(opened).toEqual({ ...flipped, mode: "on" });
});
