import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

for (const width of [1440, 390])
  for (const theme of ["light", "dark"] as const) {
    test(`P0-TILO-APPS public capture under Hosting CSP ${width} ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 850 });
      await page.emulateMedia({ colorScheme: theme });
      const csp =
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src 'self' data: blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
      await page.route("**/u/ada/survey", async (route) => {
        const response = await route.fetch();
        await route.fulfill({
          response,
          headers: {
            ...response.headers(),
            "content-security-policy": csp,
            "referrer-policy": "no-referrer",
          },
        });
      });
      let posts = 0;
      await page.route("**/public/apps/ada/survey**", async (route) => {
        if (route.request().method() === "POST") {
          posts++;
          expect(route.request().postDataJSON()).toEqual({ fields: { name: "Ada" }, website: "" });
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: '{"response_id":"r1","count":1}',
          });
        } else {
          await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
              title: "Survey",
              html: '<form><label>Name <input name="name"></label><button>Send</button></form>',
            }),
          });
        }
      });
      await page.goto("/u/ada/survey");
      await expect(page.getByText("Made with Tilo")).toBeVisible();
      await expect(page.locator("nav")).toHaveCount(0);
      const frame = page.frameLocator("iframe");
      await frame.locator('input[name="name"]').fill("Ada");
      await frame.getByRole("button", { name: "Send" }).click();
      await expect.poll(() => posts).toBe(1);
      await expect(page.getByText("Thank you! Your response was saved.")).toBeVisible();
      const dir = process.env.TILO_EVIDENCE_DIR;
      if (dir) {
        await mkdir(dir, { recursive: true });
        await page.screenshot({ path: join(dir, `${width}-${theme}.png`), fullPage: true });
      }
    });
  }

test("P0-TILO-APPS owner publishes, anonymous person responds, owner downloads CSV", async ({
  page,
}) => {
  const html = '<form><label>Name <input name="name"></label><button>Send</button></form>';
  const rows: Array<{ id: string; at: string; fields: { name: string } }> = [];
  let published = false;
  await page.route("**/v1/artifacts/art_1**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/publish")) {
      if (method === "GET" && !published) return route.fulfill({ status: 404 });
      if (method === "POST") published = true;
      if (method === "DELETE") published = false;
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ app: { path: "/u/ada/survey", published } }),
      });
    }
    if (url.endsWith("/responses.csv"))
      return route.fulfill({ contentType: "text/csv; charset=utf-8", body: "name\r\nAda\r\n" });
    if (url.endsWith("/responses"))
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ count: rows.length, responses: rows }),
      });
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ title: "Survey", html }),
    });
  });
  await page.route("**/public/apps/ada/survey**", async (route) => {
    if (route.request().method() === "POST") {
      rows.push({ id: "r1", at: "2026-10-18T10:00:00Z", fields: { name: "Ada" } });
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ response_id: "r1", count: rows.length }),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ title: "Survey", html }),
    });
  });
  await page.goto("/app/art_1");
  await expect(page.getByRole("button", { name: "Publish as a website" })).toBeVisible();
  await page.getByRole("button", { name: "Publish as a website" }).click();
  await expect(page.getByRole("link", { name: /\/u\/ada\/survey/ })).toBeVisible();
  await page.goto("/u/ada/survey");
  await page.frameLocator("iframe").locator('input[name="name"]').fill("Ada");
  await page.frameLocator("iframe").getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Thank you! Your response was saved.")).toBeVisible();
  await page.goto("/app/art_1");
  await expect(page.getByText("1 responses")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.csv$/);
});
