import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 900 } });

test("P0_PERF_loading_home_reserves_the_finished_hero_height", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".park-home-top:not([role='status'])")).toBeVisible({
    timeout: 45_000,
  });
  const heights = await page.evaluate(() => {
    const top = document.querySelector<HTMLElement>(".park-home-top:not([role='status'])");
    if (!top) return { loaded: 0, loading: 0 };
    const skeleton = document.createElement("div");
    skeleton.className = "park-home-top";
    skeleton.setAttribute("role", "status");
    skeleton.innerHTML = `
      <div class="park-home-hero park-home-hero--loading">
        <span class="park-home-skeleton park-home-skeleton--short"></span>
        <span class="park-home-skeleton park-home-skeleton--wide"></span>
        <span class="park-home-skeleton park-home-skeleton--mid"></span>
      </div>`;
    top.before(skeleton);
    const result = {
      loaded: top.getBoundingClientRect().height,
      loading: skeleton.getBoundingClientRect().height,
    };
    skeleton.remove();
    return result;
  });
  expect(heights.loading).toBeGreaterThanOrEqual(heights.loaded);
});

test("P0_PERF_home_hint_reserves_its_loaded_font_height", async ({ page }) => {
  await page.route("**/*.woff*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 4500));
    await route.continue();
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const hint = page.locator(".park-home-hint");
  await expect
    .poll(() => hint.evaluate((element) => element.getBoundingClientRect().height))
    .toBeGreaterThan(0);
  const dimensions = await hint.evaluate((element) => ({
    height: element.getBoundingClientRect().height,
    lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
    fontStatus: document.fonts.status,
  }));
  expect(dimensions.fontStatus).toBe("loading");
  expect(dimensions.height).toBeGreaterThanOrEqual(dimensions.lineHeight * 2 - 0.5);
});
