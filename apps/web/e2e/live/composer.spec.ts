// FR-UX-13 (docs/prd-supplement-design-2026-10-06.md section 1.6; HR-1..HR-7): the Park Home composer against the
// LIVE Api in a real browser. Starting work makes the real intake call (POST /intake, the legacy S-01's call);
// the world is added and the toast offers Open only after the server's reply. The page is /park/home, served by a
// Vite with VITE_TILO_API_URL set (the fake tilo-api of e2e/support/fakeCardsApi.mjs answers the reads); the
// intake route is stubbed here with `page.route`, held until the test releases it, so no real backend is used.
// Local only (TILO_LIVE=1): `TILO_LIVE=1 pnpm exec playwright test e2e/live/composer --project=live --workers=1`.
import { type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const CORS = { "access-control-allow-origin": "*", "content-type": "application/json" };
const BRIEF = {
  goal: "Compare three suppliers' quotes and recommend one.",
  deliverables: [{ title: "Supplier comparison", format: "pdf" }],
  audience: "Operations lead",
  deadline: null,
  constraints: [],
  sources: [],
  sensitivity: "business",
  assumptions: [],
  applied_preferences: [],
};
const INTAKE = { task_id: "t_e2e_1", brief: BRIEF, questions: [], files: [] };

interface Stub {
  posts: () => number;
  texts: () => string[];
  release: (status?: number, body?: unknown) => void;
}

/** Holds the first POST /intake until `release`, and records how many arrived and what text they carried. */
async function stubIntake(page: Page): Promise<Stub> {
  let count = 0;
  const texts: string[] = [];
  let release: (r: { status: number; body: unknown }) => void = () => undefined;
  const held = new Promise<{ status: number; body: unknown }>((r) => {
    release = r;
  });
  await page.route(`${API}/intake`, async (route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.fulfill({ status: 204, headers: CORS });
    count += 1;
    texts.push(req.postData() ?? "");
    const r = await held;
    await route.fulfill({ status: r.status, headers: CORS, body: JSON.stringify(r.body) });
  });
  return {
    posts: () => count,
    texts: () => texts,
    release: (status = 200, body: unknown = INTAKE) => release({ status, body }),
  };
}

async function planFor(page: Page, text: string) {
  await page.goto("/park/home");
  const box = page.getByLabel("Describe your task");
  await expect(box).toBeVisible({ timeout: 30_000 });
  await box.fill(text);
  await page.getByRole("button", { name: "Start task" }).click();
  await expect(page.getByRole("button", { name: "Start now" })).toBeVisible();
}

test("FR_UX_13_e2e_live_start_adds_the_world_and_toasts_with_Open_only_after_the_server_replies", async ({
  page,
}) => {
  const intake = await stubIntake(page);
  await planFor(page, "Compare three suppliers");
  const start = page.getByRole("button", { name: "Start now" });
  await start.click();

  // The POST is out and the reply is held: nothing is shown as started (HR-1), and a second tap sends nothing.
  await expect.poll(intake.posts).toBe(1);
  await start.click({ force: true, timeout: 1000 }).catch(() => undefined);
  await page.waitForTimeout(400);
  expect(await page.getByRole("button", { name: "Open", exact: true }).count()).toBe(0);
  expect(intake.posts(), "one POST for one start").toBe(1);
  expect(intake.texts()[0] ?? "").toContain("Compare three suppliers");

  intake.release();
  const open = page.getByRole("status").getByRole("button", { name: "Open", exact: true });
  await expect(open).toBeVisible();
  expect(intake.posts()).toBe(1);

  await open.click();
  await expect(page).toHaveURL(/\/(park\/world\/t_e2e_1|task\/t_e2e_1\/understanding)$/);
});

test("FR_UX_13_e2e_live_not_signed_in_asks_to_sign_in_adds_no_world_and_keeps_the_text", async ({
  page,
}) => {
  const intake = await stubIntake(page);
  await planFor(page, "Compare three suppliers");
  await page.getByRole("button", { name: "Start now" }).click();
  await expect.poll(intake.posts).toBe(1);
  intake.release(401, { detail: "Unauthorized" });

  await expect(page.getByText(/sign in/i).first()).toBeVisible();
  expect(await page.getByRole("button", { name: "Open", exact: true }).count()).toBe(0);
  await expect(page.getByLabel("Describe your task")).toHaveValue("Compare three suppliers");
  expect(intake.posts(), "no retry").toBe(1);
});
