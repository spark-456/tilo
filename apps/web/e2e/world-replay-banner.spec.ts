import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";
import { fixtureReplayLabel, fixtureUrl } from "./support/world";

// P6 / HR-4 + BQ-07: "in fixture mode a permanent label containing 'Fixture replay' is visible
// at all times at 1440x900, 390x844 and 1920x1080 (?display=stage), not covered by other
// elements, not dismissable, exposed to assistive tech (role="status" or inside a labelled
// region)."
//
// BQ-07 (docs/open-questions.md) is what picks "Fixture replay" over HR-4's literal "Replay of
// run #… recorded [date]" wording: a fixture stream is dev data, not a real recorded run, so it
// must never claim to be one ("Dev fixture only; never shown as a replay of a real run").

const STAGE = { width: 1920, height: 1080 } as const;
const VIEWPORTS = {
  desktop: { viewport: DESKTOP, extra: {} },
  mobile: { viewport: MOBILE, extra: {} },
  stage: { viewport: STAGE, extra: { display: "stage" } },
} as const;

for (const [name, { viewport, extra }] of Object.entries(VIEWPORTS)) {
  test.describe(`${name} replay banner`, () => {
    test.use({ viewport });

    test(`HR-4/BQ-07 replay banner: "Fixture replay" is visible and not covered at ${name} size`, async ({
      page,
    }) => {
      await page.goto(fixtureUrl("village-basic", { seq: 10, ...extra }));
      const label = fixtureReplayLabel(page);
      await expect(label).toBeVisible();
      await expect(label).toContainText(/Fixture replay/i);

      const box = await label.boundingBox();
      expect(box, "the Fixture replay label has no layout box").not.toBeNull();
      if (box) {
        expect(box.width).toBeGreaterThan(0);
        expect(box.height).toBeGreaterThan(0);
        // Not covered: the element found at the label's own centre point must be the label
        // itself (or a descendant of it), not some other element painted on top.
        const isOnTop = await page.evaluate(
          ({ x, y, testId }) => {
            const el = document.elementFromPoint(x, y);
            const label = document.querySelector(`[data-testid="${testId}"]`);
            return !!el && !!label && (label === el || label.contains(el));
          },
          { x: box.x + box.width / 2, y: box.y + box.height / 2, testId: "fixture-replay-banner" },
        );
        expect(isOnTop, "another element is painted over the Fixture replay label").toBe(true);
      }
    });

    test(`HR-4/BQ-07 replay banner: stays visible after the run finishes and is not dismissable at ${name} size`, async ({
      page,
    }) => {
      await page.goto(fixtureUrl("village-basic", { seq: 44, ...extra }));
      const label = fixtureReplayLabel(page);
      await expect(label).toBeVisible();
      await page.waitForTimeout(500);
      await expect(label, "the banner must be permanent, not a toast that times out").toBeVisible();
    });

    test(`HR-4/BQ-07 replay banner: exposed to assistive tech at ${name} size`, async ({
      page,
    }) => {
      await page.goto(fixtureUrl("village-basic", { seq: 1, ...extra }));
      const label = fixtureReplayLabel(page);
      await expect(label).toBeVisible();

      const accessible = await page.evaluate((testId) => {
        const el = document.querySelector(`[data-testid="${testId}"]`);
        if (!el) return { found: false };
        const role = el.getAttribute("role") ?? el.closest("[role]")?.getAttribute("role") ?? null;
        const labelledRegion = el.closest("[role][aria-label], [role][aria-labelledby]");
        return { found: true, role, hasLabelledRegion: !!labelledRegion };
      }, "fixture-replay-banner");

      expect(accessible.found, '[data-testid="fixture-replay-banner"] was not found').toBe(true);
      expect(
        accessible.role === "status" || accessible.hasLabelledRegion,
        'the Fixture replay label needs role="status" or a labelled containing region',
      ).toBe(true);
    });
  });
}
