// WEB-CUTOVER acceptance (docs/web-app-rebuild-plan.md sections 1, 3, 8): the Park app is the app at the
// ROOT paths. / /worlds /world/<id> /team /connectors /skills /agenda /ledger /profile load their Park page
// with no console errors; /park/<page> still works as an alias; the nav writes root paths; the old screens
// keep their addresses, with the stage moved to /world/<id>/stage, S-18 at /team/console.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-cutover.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { watchConsole } from "./support/screens";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

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

// ---- the fix pass: real intake stays reachable, unknown paths are Park "Not found", samples have no stage ----

const NO_STAGE = "Sample world: there is no recorded run to open";

for (const path of ["/xyz", "/world/x/unknown", "/start/x", "/team/x"]) {
  test(`WEB_CUTOVER_e2e_${path.slice(1).replace(/\//g, "_")}_is_the_park_not_found_with_a_home_link`, async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await page.goto(path);
    const nf = page.getByTestId("park-not-found");
    await expect(nf).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(nf.getByRole("link", { name: "Go to Home" })).toHaveAttribute("href", "/");
    // never the old Start screen
    await expect(page.getByLabel("Describe your task")).toHaveCount(0);
    expect(problems).toEqual([]);
  });
}

test("WEB_CUTOVER_e2e_the_not_found_home_link_goes_home", async ({ page }) => {
  await page.goto("/xyz");
  await page.getByTestId("park-not-found").getByRole("link", { name: "Go to Home" }).click();
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/");
});

test("WEB_CUTOVER_e2e_start_is_the_intake_form", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/start");
  await expect(page.getByLabel("Describe your task")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeVisible();
  await expect(page.locator("[data-park]")).toHaveCount(0);
  expect(problems).toEqual([]);
});

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["phone", MOBILE],
] as const) {
  test(`WEB_CUTOVER_e2e_home_${name}_start_a_real_task_links_to_the_intake_without_a_layout_shift`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await watchShifts(page);
    const problems = collectConsoleProblems(page);
    await page.goto("/");
    const link = page.getByRole("link", { name: "Start a real task", exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/start");
    // inside the viewport, clear of the composer panel above it, big enough to hit
    const box = await link.boundingBox();
    const panel = await page.locator(".park-home-panel").boundingBox();
    if (!box || !panel) throw new Error("no boxes");
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    expect(box.y).toBeGreaterThanOrEqual(panel.y + panel.height - 0.5);
    expect(box.height).toBeGreaterThanOrEqual(24);
    // the composer stays where the design puts it: its panel's bottom edge is the column's bottom edge
    expect(await readShifts(page)).toEqual([]);
    await Promise.all([page.waitForURL(/\/start$/), link.click()]);
    await expect(page.getByLabel("Describe your task")).toBeVisible();
    expect(problems).toEqual([]);
  });
}

test("WEB_CUTOVER_e2e_a_sample_world_has_a_disabled_live_view_and_nothing_to_open", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/world/k1");
  const world = page.getByTestId("park-page-world");
  await expect(world).toBeVisible();
  const live = world.getByRole("link", { name: "Open live view" });
  await expect(live).toBeVisible();
  await expect(live).toHaveAttribute("aria-disabled", "true");
  await expect(live).not.toHaveAttribute("href", /.*/);
  await expect(live).toHaveAttribute("title", NO_STAGE);
  for (const lens of ["Story", "Trace", "Delivery", "Inspect"]) {
    const a = world
      .getByRole("navigation", { name: "Run views" })
      .getByRole("link", { name: lens });
    await expect(a, lens).toHaveAttribute("aria-disabled", "true");
    await expect(a, lens).not.toHaveAttribute("href", /.*/);
  }
  await expect(world.getByText(NO_STAGE).first()).toBeAttached();
  await live.click({ force: true }); // Playwright treats aria-disabled as not clickable
  await expect(page).toHaveURL(/\/world\/k1$/);
  await expect(world).toBeVisible();
  expect(problems).toEqual([]);
});
