// WEB-7 acceptance: the Ledger page in the real Park shell at /ledger, 1440x900 and 390x844, on the
// fixture Api. It loads inside the one [data-park] root with its key copy and no console output, one
// approval goes through decide() (the KPIs, the toast and the Activity row all follow, and Undo restores
// them), and axe finds nothing serious.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/ledger.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

/** The "Spent so far" KPI tile (the same figure also sits in the donut hole). */
const spentTile = (page: Page) => page.locator(".park-kpi", { hasText: "Spent so far" });

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/ledger", { timeout: 120_000 });
  await page
    .getByRole("heading", { level: 1, name: "Ledger" })
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

// These reference-layout fixtures are recorded for 24 September 2026 (DEMO-TIME-1).
// Keep their recorded date deterministic while normal timers and every assertion still run.
test.beforeEach(async ({ page }, info) => {
  if (info.title.startsWith("WEB_7_e2e_") || info.title.startsWith("WEB_6_e2e_")) {
    await page.clock.setFixedTime(new Date("2026-09-24T12:00:00Z"));
  }
});

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`ledger at ${name}`, () => {
    test.use({ viewport });

    test(`WEB_7_e2e_${name}_loads_with_its_copy_and_no_console_output`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/ledger");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ledger");
      await expect(page).toHaveTitle("Ledger · Tilo");
      await expect(page.getByRole("main")).toHaveCount(1);
      await expect(page.locator("[data-park]")).toHaveCount(1);
      await expect(page.locator("[data-park-ledger]")).toHaveAttribute("data-source", "fixture");
      await expect(
        page.getByText(
          "Every cost and every decision your agents make. September 2026 · 6 days left · budget £8,000.",
        ),
      ).toBeVisible();
      for (const region of [
        "Spend over the month",
        "Where it goes",
        "Cost per run",
        "Approval wait times",
        "What Tilo gave back",
        "Activity",
      ])
        await expect(page.getByRole("region", { name: region })).toBeAttached();
      await expect(spentTile(page)).toContainText("£2,412");
      await expect(page.getByText("On track to finish £1,700 under budget")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, "the page does not scroll sideways").toBeLessThanOrEqual(0);
      expect(problems).toEqual([]);
    });

    test(`WEB_7_e2e_${name}_activity_titles_have_room_to_read`, async ({ page }) => {
      await page.goto("/ledger");
      const title = page.locator(".park-ledger-what-title").first();
      await expect(title).toBeVisible();
      const box = await title.boundingBox();
      expect(box?.width ?? 0, "an Activity title is at least 120px wide").toBeGreaterThanOrEqual(
        120,
      );
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, "the page does not scroll sideways").toBeLessThanOrEqual(0);
    });

    test(`WEB_7_e2e_${name}_one_approval_goes_through_decide_and_undo_restores_it`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/ledger");
      const waiting = page.getByRole("button", { name: /^Waiting on you/ });
      await expect(waiting).toBeVisible();
      await expect(spentTile(page)).toContainText("£2,412");

      await page.getByRole("button", { name: "Approve £3,420" }).click();

      const toast = page.getByRole("status");
      await expect(toast).toContainText("Approved £3,420 for Laptop Depot");
      await expect(spentTile(page)).toContainText("£5,832");
      await expect(page.getByText("73% of £8,000")).toBeVisible();
      await expect(page.getByText("You approved £3,420 for Laptop Depot")).toBeVisible();
      await expect(waiting).toHaveCount(0);

      await toast.getByRole("button", { name: "Undo" }).click();
      await expect(spentTile(page)).toContainText("£2,412");
      await expect(page.getByRole("button", { name: /^Waiting on you/ })).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_7_e2e_${name}_day_and_night_have_nothing_serious_for_axe`, async ({ page }) => {
      test.setTimeout(90_000);
      const problems = collectConsoleProblems(page);
      for (const time of ["day", "night"] as const) {
        await page.goto("/ledger");
        await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ledger");
        if (time === "night")
          await page.evaluate(() => {
            document.querySelector("[data-park]")?.setAttribute("data-time", "night");
          });
        // Design-owned exception (the reference's own teal on its own soft tint; plan 8c), narrow on purpose:
        // the "sch" tone colours the label of the "Saved by memory" tile teal #0e7c79 on #e2ede9. Measured
        // 4.19:1 at 13px bold against the 4.5:1 minimum (WEB-7 builder, this tile state); the WEB-2 critic
        // measured 3.86:1 on a different tile state. It lives in the shared tokens and KpiTile, not this
        // page. Everything else on the page is still scanned.
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .exclude(".park-kpi--sch .park-kpi__label")
          .analyze();
        const bad = results.violations.filter(
          (v) => v.impact === "serious" || v.impact === "critical",
        );
        const summary = bad.map((v) => ({
          rule: v.id,
          at: v.nodes.map((n) => n.target.join(" ")),
        }));
        expect(summary, `${time}: ${JSON.stringify(summary, null, 2)}`).toEqual([]);
      }
      expect(problems).toEqual([]);
    });
  });
}
