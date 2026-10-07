// WEB-3b: the page column (where every page sheet sits) is where the reference puts it (measured on `Tilo App.dc.html`): x=60 and width 1320
// at 1440 (the 1320 column centred, 24px side padding inside a 1392 box), x=24 and width 342 at 390 (the
// column is the window less the 24px side padding).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-column.spec.ts --project=chromium --no-deps --workers=3
import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const CASES = [
  ["desktop", DESKTOP, { x: 60, width: 1320 }],
  ["mobile", MOBILE, { x: 24, width: 342 }],
] as const;

for (const [name, viewport, want] of CASES) {
  test.describe(`park page column at ${name}`, () => {
    test.use({ viewport });

    for (const path of ["/ledger", "/worlds"]) {
      test(`WEB_3b_e2e_${name}_the_page_column_of_${path.slice(1)}_is_at_x_${want.x}_width_${want.width}`, async ({
        page,
      }) => {
        test.setTimeout(150_000);
        await page.goto(path, { timeout: 120_000 });
        const sheet = page
          .getByTestId(/^park-page-/)
          .locator(".park-sheet")
          .first();
        await expect(sheet).toBeVisible({ timeout: 120_000 });
        const box = await sheet.boundingBox();
        expect([box?.x, box?.width]).toEqual([want.x, want.width]);
      });
    }
  });
}
