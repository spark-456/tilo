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
