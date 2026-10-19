import { expect, test } from "@playwright/test";
test.use({ viewport: { width: 1280, height: 900 } });
for (const [path, destination, title] of [
  ["/mail", "/team?focus=mail", "Email Autopilot"],
  ["/team/console", "/team?focus=console", "Team Lead console"],
  ["/connections", "/connectors", "Connectors"],
  ["/more", "/more", "More"],
] as const) {
  test(`OLD-UI-OUT-4b ${path} opens in Park and preserves the run`, async ({ page }) => {
    await page.goto(`${path}?world=w_sample_village_basic`);
    const separator = destination.includes("?") ? "&" : "?";
    await expect(page).toHaveURL(
      new RegExp(`${destination}${separator}world=w_sample_village_basic$`.replace(/[?]/g, "\\?")),
    );
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(page.locator(".flow-shell")).toHaveCount(0);
  });
}
