// #227 Bundle G2 part A (S-13, S-16, S-17, S-18): every key figure says in words what it means,
// the sections follow their importance, and S-13's search is a real one (no dashed ghost buttons).
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const tile = (page: import("@playwright/test").Page, screenId: string, label: string) =>
  page.getByTestId(screenId).locator("li", { hasText: label }).first();

test("UX-1 G2a figures carry a state chip in words on S-13, S-17 and S-18 (HR-1)", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  // Recorded pace: at the start nothing has happened, and the chips say so.
  await page.goto("/library");
  await expect(tile(page, "library", "Deliverables")).toContainText("None yet");
  await expect(tile(page, "library", "Memory reuses")).toContainText("None yet");
  await page.goto("/mail");
  await expect(tile(page, "mail", "Waiting for you")).toContainText("All clear");
  await expect(tile(page, "mail", "Replies sent")).toContainText("None yet");
  await page.goto("/team");
  await expect(tile(page, "team-lead", "Questions waiting")).toContainText("All clear");
  // After the run: the same figures change their words with their numbers.
  await page.goto("/library?speed=100");
  await expect(tile(page, "library", "Deliverables")).toContainText("Delivered", {
    timeout: 20_000,
  });
  await page.goto("/mail?speed=100");
  await expect(tile(page, "mail", "Replies sent")).toContainText("Sent", { timeout: 20_000 });
  await page.goto("/team?speed=100");
  await expect(tile(page, "team-lead", "Answers recorded")).toContainText("Recorded", {
    timeout: 20_000,
  });
  expect(problems).toEqual([]);
});

test("UX-1 G2a S-13 search narrows the deliverables and says so when nothing matches", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(MOBILE);
  await page.goto("/library?speed=100");
  const rows = page.getByTestId("library-rows");
  await expect(rows).toContainText("Triage list", { timeout: 20_000 });
  const search = page.getByRole("searchbox", { name: "Search the library" });
  await search.fill("triage");
  await expect(rows).toContainText("Triage list");
  await search.fill("zzz");
  await expect(page.getByTestId("library-nomatch")).toBeVisible();
  await expect(rows).not.toContainText("Triage list");
  await search.fill("");
  await expect(rows).toContainText("Triage list");
  await expect(page.getByRole("button", { name: /Forget a memory item/ })).toHaveCount(0);
});

test("UX-1 G2a sections follow their importance: S-17 Drafts before Triage, S-16 messages before Email", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  const order = async (path: string) =>
    page.goto(path).then(() => page.locator("main section.screen-section h2").allTextContents());
  const mail = await order("/mail");
  expect(mail.indexOf("Drafts")).toBeLessThan(mail.indexOf("Triage"));
  expect(mail.indexOf("Sent")).toBeLessThan(mail.indexOf("Triage"));
  const channels = await order("/channels");
  expect(channels.indexOf("Recent channel messages")).toBeLessThan(channels.indexOf("Email"));
});

test("UX-1 S-17 the How we estimate link is a 44 px target on a phone", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(MOBILE);
  await page.goto("/mail?speed=100");
  const link = page.getByRole("link", { name: "How we estimate" });
  await expect(link).toBeVisible({ timeout: 20_000 });
  expect((await link.boundingBox())?.height).toBeGreaterThanOrEqual(44);
});
