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

test("OLD_UI_OUT_3_e2e_the_old_replays_address_lands_on_the_park_worlds_page", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/worlds/replays");
  await expect(page.locator("[data-park]")).toHaveCount(1);
  await expect(page).toHaveURL(/\/worlds$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(problems).toEqual([]);
});

test("OLD_UI_OUT_3_e2e_the_old_meetings_plate_and_library_addresses_land_on_park_pages", async ({
  page,
}) => {
  const problems = watchConsole(page);
  for (const [from, to] of [
    ["/meetings", /\/agenda$/],
    ["/pinboards", /\/agenda$/],
    ["/calendar", /\/agenda$/],
    ["/plate", /\/$/],
    ["/library/artifacts", /\/library$/],
  ] as const) {
    await page.goto(from);
    await expect(page.locator("[data-park]"), from).toHaveCount(1);
    await expect(page, from).toHaveURL(to);
  }
  await expect(page.getByTestId("park-page-library")).toBeVisible();
  expect(problems).toEqual([]);
});

test("OLD_UI_OUT_e2e_the_retired_task_and_start_addresses_go_to_the_park_home", async ({
  page,
}) => {
  const problems = watchConsole(page);
  for (const path of [`/task/${TASK}/understanding`, `/task/${TASK}/approaches`, "/start"]) {
    await page.goto(path);
    await expect(page.getByTestId("park-page-home")).toBeVisible();
    expect(new URL(page.url()).pathname, path).toBe("/");
    await expect(page.locator("main h1, h1").filter({ hasText: "Understanding" })).toHaveCount(0);
  }
  expect(problems).toEqual([]);
});

// ---- the fix pass: real intake stays reachable, unknown paths are Park "Not found", samples have no stage ----

const NO_STAGE = "Live view is for real runs";

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

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["phone", MOBILE],
] as const) {
  test(`W-HOME-RED_WEB_CUTOVER_e2e_home_${name}_starts_in_the_park_composer_without_a_layout_shift`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await watchShifts(page);
    const problems = collectConsoleProblems(page);
    await page.goto("/");
    // SIMPLE-RUN-1 (#1077) and RETIRE-OLD-APP: task start lives on Park Home.
    // Home.start.test.tsx pins the removal of the legacy intake link.
    const input = page.getByLabel("Describe your task");
    const start = page.getByRole("button", { name: "Start task", exact: true });
    await expect(input).toBeVisible();
    await expect(start).toBeVisible();
    await expect(page.getByRole("link", { name: "Start a real task", exact: true })).toHaveCount(0);
    // Inside the viewport and the composer panel, big enough to hit.
    const box = await start.boundingBox();
    const panel = await page.locator(".park-home-panel").boundingBox();
    if (!box || !panel) throw new Error("no boxes");
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    expect(box.y).toBeGreaterThanOrEqual(panel.y);
    expect(box.y + box.height).toBeLessThanOrEqual(panel.y + panel.height);
    expect(box.height).toBeGreaterThanOrEqual(24);
    // the composer stays where the design puts it: its panel's bottom edge is the column's bottom edge
    expect(await readShifts(page)).toEqual([]);
    await input.fill("Plan a launch");
    await start.click();
    await expect(page.getByRole("button", { name: "Start now", exact: true })).toBeVisible();
    await expect(input).toHaveValue("Plan a launch");
    expect(new URL(page.url()).pathname).toBe("/");
    await expect(page.getByTestId("park-page-home")).toBeVisible();
    expect(problems).toEqual([]);
  });
}

// POLISH-2: no disabled link is offered at all; one chip says why.
test("WEB_CUTOVER_e2e_a_sample_world_has_a_disabled_live_view_and_nothing_to_open", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/world/k1");
  const world = page.getByTestId("park-page-world");
  await expect(world).toBeVisible();
  await expect(world.getByRole("link", { name: "Open live view" })).toHaveCount(0);
  await expect(world.getByRole("navigation", { name: "Run views" })).toHaveCount(0);
  await expect(world.getByText(NO_STAGE).first()).toBeVisible();
  await expect(page).toHaveURL(/\/world\/k1$/);
  expect(problems).toEqual([]);
});
