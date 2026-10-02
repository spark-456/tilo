// AGW-08 smoke: one test per "Coming soon" screen (PRD 18.3). Group B replaces a stub's test with
// the real screen's own when it builds the screen. Names carry the screen id.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { expectNoDeadControls, watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const STUBS: ReadonlyArray<readonly [string, string, string]> = [
  ["S_06", "/needs-you", "Needs-you queue and card"],
  ["S_07", "/needs-you/gate", "Gate sheet"],
  ["S_08", "/needs-you/consent", "Connection consent sheet"],
  ["S_09", "/meeting", "Meeting"],
  ["S_13", "/library", "Library and Memory Vault"],
  ["S_14", "/worlds", "Worlds list and replays"],
  ["S_15", "/autonomy", "Autonomy"],
  ["S_16", "/channels", "Channels"],
  ["S_17", "/mail", "Email Autopilot home"],
  ["S_18", "/team", "Team Lead console"],
  ["S_19", "/connections", "Connections"],
  ["S_21", "/library/artifacts", "Artifact history and restore"],
  ["S_22", "/settings", "Settings"],
  ["S_23", "/estimate", "How we estimate; status page"],
  ["S_24", "/pilot", "Pilot diary and survey"],
];

for (const [id, path, name] of STUBS) {
  test(`${id} renders, no console errors, placeholders aria-disabled`, async ({ page }) => {
    test.setTimeout(90_000); // two viewports and an axe run, under a parallel suite
    const problems = watchConsole(page);
    for (const viewport of [DESKTOP, MOBILE]) {
      await page.setViewportSize(viewport);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expect(page.getByTestId("coming-soon")).toContainText("Coming soon");
      await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
      await expectNoDeadControls(page);
    }
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations).toEqual([]);
    expect(problems).toEqual([]);
  });
}

test("AGW-08 /screens lists every screen id with built or placeholder status and a link", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto("/screens");
  await expect(page.getByRole("heading", { level: 1, name: "Screens" })).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(25);
  await expect(rows.first()).toContainText("S-01");
  await expect(rows.last()).toContainText("S-25");
  // Each linked screen opens: follow the S-13 link.
  await page.getByRole("link", { name: "Library and Memory Vault" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Library and Memory Vault" }),
  ).toBeVisible();
  expect(page.url()).toMatch(/\/library$/);
  expect(problems).toEqual([]);
});

test("AGW-08 More reaches every screen the tabs do not, and nav links navigate", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.setViewportSize(MOBILE);
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: /primary/i });
  await nav.getByRole("link", { name: "More" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "More" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "More" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Autonomy" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Autonomy" })).toBeVisible();
  await nav.getByRole("link", { name: "Library" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Library and Memory Vault" }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "Autonomy" })).toBeVisible();
  expect(problems).toEqual([]);
});
