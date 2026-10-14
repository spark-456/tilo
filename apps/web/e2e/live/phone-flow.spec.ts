// SIMPLE-RUN-1 (supersedes the FR-UX-13 plan-card flow; HR-1..HR-7): the Park Home composer against the LIVE Api in a
// real browser. Start makes the real intake call, skips every question, prices the recommended approach and shows ONE
// confirm card; the card's Start is the approval and opens the run's world. The page is /park/home, served by a Vite
// with VITE_TILO_API_URL set (the fake tilo-api of e2e/support/fakeCardsApi.mjs answers the reads); the task routes are
// stubbed here with `page.route`, so no real backend is used. Nothing sends the person to the old Understanding screen.
// Local only (TILO_LIVE=1): `TILO_LIVE=1 pnpm exec playwright test e2e/live/composer --project=live --workers=1`.
import { type Page, expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
});

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "content-type": "application/json",
};
const BRIEF = {
  goal: `Compare three suppliers' quotes and recommend one. ${"Supplier".repeat(40)}`,
  deliverables: [{ title: "Supplier comparison", format: "pdf" }],
  audience: "Operations lead",
  deadline: null,
  constraints: [],
  sources: [],
  sensitivity: "business",
  assumptions: [],
  applied_preferences: [],
};
const QUESTIONS = [{ field: "audience", text: "Who is it for?", suggested_answers: ["The team"] }];
const INTAKE = { task_id: "t_e2e_1", brief: BRIEF, questions: QUESTIONS, files: [] };
const APPROACH = {
  id: "a_balanced",
  label: "Balanced",
  summary: "Read the quotes, then compare.",
  dimensions: {
    depth: "standard",
    sources: "files",
    parallelism: "single",
    verification: "light",
    output_format: "document",
  },
  time: { min_s: 120, max_s: 300 },
  credits: { min: 8, max: 20 },
  risks: [],
  skips: [],
};

interface Stub {
  posts: () => string[];
  release: (status?: number, body?: unknown) => void;
}

/** Holds the first POST /intake until `release`; every later task route answers at once. Records each POST path. */
async function stubTask(page: Page): Promise<Stub> {
  const posts: string[] = [];
  let release: (r: { status: number; body: unknown }) => void = () => undefined;
  const held = new Promise<{ status: number; body: unknown }>((r) => {
    release = r;
  });
  const reply = (body: unknown, status = 200) => ({
    status,
    headers: CORS,
    body: JSON.stringify(body),
  });
  await page.route(`${API}/intake`, async (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ status: 204, headers: CORS });
    posts.push("/intake");
    const r = await held;
    await route.fulfill(reply(r.body, r.status));
  });
  await page.route(`${API}/tasks/t_e2e_1/answers`, async (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ status: 204, headers: CORS });
    posts.push("/answers");
    await route.fulfill(
      reply({
        brief: { ...BRIEF, assumptions: [{ question: "Who is it for?", assumed: "The team" }] },
      }),
    );
  });
  await page.route(`${API}/tasks/t_e2e_1/approaches`, (route) =>
    route.request().method() !== "GET"
      ? route.fulfill({ status: 204, headers: CORS })
      : route.fulfill(
          reply({
            task_id: "t_e2e_1",
            approaches: [APPROACH],
            recommended: "a_balanced",
            credit_usd: 0.05,
          }),
        ),
  );
  await page.route(`${API}/tasks/t_e2e_1/approve`, async (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ status: 204, headers: CORS });
    posts.push("/approve");
    await route.fulfill(reply({ world_id: "w_here" }));
  });
  return {
    posts: () => posts,
    release: (status = 200, body: unknown = INTAKE) => release({ status, body }),
  };
}

async function typeTask(page: Page, text: string) {
  await page.goto("/park/home");
  const box = page.getByLabel("Describe your task");
  await expect(box).toBeVisible({ timeout: 30_000 });
  await box.fill(text);
}

async function fits(page: Page, selector: string) {
  const boxes = await page.locator(selector).evaluateAll((els) =>
    els.map((el) => {
      const box = el.getBoundingClientRect();
      return {
        left: box.left,
        right: box.right,
        width: box.width,
        height: box.height,
        clipped: el.scrollWidth > el.clientWidth + 1,
      };
    }),
  );
  expect(boxes.length).toBeGreaterThan(0);
  for (const box of boxes) {
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(390);
    expect(box.clipped).toBe(false);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
}

async function target(page: Page, selector: string) {
  for (const button of await page.locator(selector).all()) {
    await button.scrollIntoViewIfNeeded();
    const box = await button.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
}

test("M2-PHONE-1 composer, long confirm card, edit and Start fit 390x844", async ({ page }) => {
  const stub = await stubTask(page);
  await typeTask(page, "Compare three suppliers");
  await target(page, ".park-home-start");
  await fits(page, ".park-home-input");
  await page.getByRole("button", { name: "Start task" }).click();
  stub.release(200, { ...INTAKE, brief: { ...BRIEF, goal: "Supplier".repeat(40) } });
  await expect(page.getByTestId("run-card")).toBeVisible();
  await fits(page, ".park-home-plan, .park-home-plan__query, .park-home-step");
  await target(page, ".park-home-plan button");
  await page.getByRole("button", { name: "Change", exact: true }).click();
  await target(page, ".park-home-run__edit input, .park-home-run__edit button");
  await fits(page, ".park-home-run__edit");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".park-home-run__edit")).toHaveCount(0);
  await page.getByTestId("run-card").getByRole("button", { name: "Start", exact: true }).click();
  await expect(page).toHaveURL(/\/world\/w_here/);
  expect(stub.posts().filter((p) => p === "/approve")).toHaveLength(1);
  await expect(page.locator(".park-world-root")).toBeVisible();
  await fits(page, ".park-world-root");
  await page.screenshot({ path: "phone-world-390.png" });
});

test("M2-PHONE-1 Needs-you approve target fits and answers once at 390x844", async ({ page }) => {
  await page.request.post(`${API}/__control`, { data: { reset: true } });
  await page.goto("/park/worlds");
  const card = page.locator(".park-worlds-dec").filter({ hasText: "Pick a supplier shortlist" });
  await expect(card).toBeVisible();
  await fits(page, ".park-worlds-dec");
  await target(page, ".park-worlds-dec button");
  await card.getByRole("button", { name: "Go on", exact: true }).click();
  await expect(card.getByRole("button", { name: "Go on", exact: true })).toHaveCount(0);
  const entries = await (await page.request.get(`${API}/__log`)).json();
  expect(entries.filter((entry: { method: string }) => entry.method === "POST")).toHaveLength(1);
  await page.screenshot({ path: "phone-needs-you-390.png" });
});
