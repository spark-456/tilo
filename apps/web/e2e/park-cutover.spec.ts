// WEB-CUTOVER acceptance (docs/web-app-rebuild-plan.md sections 1, 3, 8): the Park app is the app at the
// ROOT paths. / /worlds /world/<id> /team /connectors /skills /agenda /ledger /profile load their Park page
// with no console errors; /park/<page> still works as an alias; the nav writes root paths; the old screens
// keep their addresses, with the stage moved to /world/<id>/stage, S-18 at /team/console.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-cutover.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { watchConsole } from "./support/screens";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

const ROOT_PAGES = [
  ["/", "home"],
  ["/worlds", "worlds"],
  ["/world/k1", "world"],
  ["/team", "team"],
  ["/connectors", "connectors"],
  ["/skills", "skills"],
  ["/agenda", "agenda"],
  ["/ledger", "ledger"],
  ["/profile", "profile"],
] as const;

const STAGE_WORLD = "w_village_basic";
const TASK = "task_fixture_1";

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it once.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/", { timeout: 120_000 });
  await page
    .getByTestId("park-page-home")
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

const tab = (page: Page, name: string) =>
  page.locator("header nav").getByRole("link", { name: new RegExp(`^${name}`) });

for (const [path, id] of ROOT_PAGES) {
  test(`WEB_CUTOVER_e2e_${id}_loads_at_${path === "/" ? "root" : path.slice(1).replace("/", "_")}_with_no_console_errors`, async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await page.goto(path);
    await expect(page.getByTestId(`park-page-${id}`)).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(1);
    expect(new URL(page.url()).pathname).toBe(path);
    expect(problems).toEqual([]);
  });
}

test("WEB_CUTOVER_e2e_the_park_alias_still_loads", async ({ page }) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/park/worlds");
  await expect(page.getByTestId("park-page-worlds")).toBeVisible();
  await page.goto("/park/home");
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_clicking_the_nav_tabs_changes_the_address_to_the_root_path", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/");
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  await tab(page, "Worlds").click();
  await expect(page).toHaveURL(/\/worlds$/);
  await expect(page.getByTestId("park-page-worlds")).toBeVisible();
  await tab(page, "Ledger").click();
  await expect(page).toHaveURL(/\/ledger$/);
  await expect(page.getByTestId("park-page-ledger")).toBeVisible();
  await tab(page, "Home").click();
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_opening_a_world_from_the_worlds_page_goes_to_world_slash_id", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/worlds");
  await expect(page.getByTestId("park-page-worlds")).toBeVisible();
  await page.locator('a[href="/world/northline"]').click();
  await expect(page).toHaveURL(/\/world\/northline$/, { timeout: 15_000 });
  await expect(page.getByTestId("park-page-world")).toBeVisible();
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_the_live_stage_is_at_world_id_stage", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto(`/world/${STAGE_WORLD}/stage`);
  await expect(page.getByTestId("stage-frame").locator("canvas")).toBeVisible();
  await expect(page.locator("[data-park]")).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_the_stage_lens_tabs_link_the_stage_and_the_lenses", async ({ page }) => {
  await page.goto(`/world/${STAGE_WORLD}/stage`);
  const lens = page.getByRole("navigation", { name: "Lens" });
  await expect(lens.getByRole("link", { name: "World" })).toHaveAttribute(
    "href",
    `/world/${STAGE_WORLD}/stage`,
  );
  await expect(lens.getByRole("link", { name: "Story" })).toHaveAttribute(
    "href",
    `/world/${STAGE_WORLD}/story`,
  );
});

test("WEB_CUTOVER_e2e_the_team_lead_console_is_at_team_console", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/team/console");
  await expect(page.getByTestId("team-lead")).toBeVisible();
  await expect(page.locator("[data-park]")).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_the_worlds_replays_list_is_at_worlds_replays", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/worlds/replays");
  await expect(page.locator("[data-park]")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(problems).toEqual([]);
});

test("WEB_CUTOVER_e2e_a_kept_task_screen_still_loads", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto(`/task/${TASK}/understanding`);
  await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
  await expect(page.locator("[data-park]")).toHaveCount(0);
  expect(problems).toEqual([]);
});
