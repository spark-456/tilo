// #227 Bundle G3 + G4: S-15 shows which autonomy level is the default by shape and text; S-22's
// Display is a segmented control whose choice applies live and is remembered.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

test("UX-1 G3 S-15 marks the default level L1 with a tick and the word, not colour alone", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto("/autonomy?speed=100");
  const levels = page.getByRole("region", { name: "Levels" });
  await expect(levels.getByText("✓ L1 · Default")).toBeVisible({ timeout: 20_000 });
  for (const id of ["L0", "L2", "L3"]) {
    await expect(levels.getByText(id, { exact: true })).toBeVisible();
  }
  await expect(levels.getByText("✓ L1 · Default")).toHaveCount(1); // one level is marked
  expect(problems).toEqual([]);
});

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["mobile", MOBILE],
] as const) {
  test(`UX-1 G4 S-22 Display is a segmented control, applied live and remembered (${name})`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/settings");
    const group = page.getByTestId("density");
    const friendly = group.getByRole("radio", { name: /Friendly/ });
    const pro = group.getByRole("radio", { name: /Professional/ });
    await expect(friendly).toBeChecked({ timeout: 20_000 });
    await expect(page.locator("html")).toHaveAttribute("data-density", "friendly");
    const gap = () =>
      page.evaluate(() =>
        getComputedStyle(document.querySelector(".app-shell") as Element)
          .getPropertyValue("--space-16")
          .trim(),
      );
    expect(await gap()).toBe("1rem");
    for (const radio of [friendly, pro]) {
      expect((await radio.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    }
    await pro.check({ force: true });
    await expect(pro).toBeChecked();
    await expect(page.locator("html")).toHaveAttribute("data-density", "professional");
    expect(await gap()).toBe("0.75rem"); // tighter, at once, no reload
    await page.reload();
    await expect(
      page.getByTestId("density").getByRole("radio", { name: /Professional/ }),
    ).toBeChecked({
      timeout: 20_000,
    });
    await page
      .getByTestId("density")
      .getByRole("radio", { name: /Friendly/ })
      .check({ force: true });
    await expect(page.locator("html")).toHaveAttribute("data-density", "friendly");
    expect(problems).toEqual([]);
  });
}
