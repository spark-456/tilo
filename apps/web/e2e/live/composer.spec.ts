// SIMPLE-RUN-1 (supersedes the FR-UX-13 plan-card flow; HR-1..HR-7): the Park Home composer against the LIVE Api in a
// real browser. Start makes the real intake call, skips every question, prices the recommended approach and shows ONE
// confirm card; the card's Start is the approval and opens the run's world. The page is /park/home, served by a Vite
// with VITE_TILO_API_URL set (the fake tilo-api of e2e/support/fakeCardsApi.mjs answers the reads); the task routes are
// stubbed here with `page.route`, so no real backend is used. Nothing sends the person to the old Understanding screen.
// Local only (TILO_LIVE=1): `TILO_LIVE=1 pnpm exec playwright test e2e/live/composer --project=live --workers=1`.
import { type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "content-type": "application/json",
};
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
    await route.fulfill(reply({ world_id: "w_e2e_1" }));
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

test("SIMPLE_RUN_1_e2e_live_start_reaches_one_confirm_card_then_its_Start_opens_the_world", async ({
  page,
}) => {
  const stub = await stubTask(page);
  await typeTask(page, "Compare three suppliers");
  await page.getByRole("button", { name: "Start task" }).click();

  // The intake is out and held: no card, nothing approved (HR-1).
  await expect.poll(() => stub.posts().length).toBe(1);
  await expect(page.getByTestId("run-card")).toHaveCount(0);

  stub.release();
  const card = page.getByTestId("run-card");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Compare three suppliers' quotes and recommend one.");
  await expect(card).toContainText("Assumed: The team");
  await expect(card).toContainText("20 credits");
  expect(stub.posts(), "intake and the one answers call; nothing approved yet").toEqual([
    "/intake",
    "/answers",
  ]);

  await card.getByRole("button", { name: "Start", exact: true }).click();
  await expect.poll(() => stub.posts().at(-1)).toBe("/approve");
  await expect(page).toHaveURL(/\/world\/w_e2e_1/);
  await expect(page).not.toHaveURL(/understanding|approaches/);
});

test("SIMPLE_RUN_1_e2e_live_not_signed_in_asks_to_sign_in_shows_no_card_and_keeps_the_text", async ({
  page,
}) => {
  const stub = await stubTask(page);
  await typeTask(page, "Compare three suppliers");
  await page.getByRole("button", { name: "Start task" }).click();
  await expect.poll(() => stub.posts().length).toBe(1);
  stub.release(401, { detail: "Unauthorized" });

  await expect(page.getByText(/sign in/i).first()).toBeVisible();
  await expect(page.getByTestId("run-card")).toHaveCount(0);
  await expect(page.getByLabel("Describe your task")).toHaveValue("Compare three suppliers");
  expect(stub.posts(), "no retry").toEqual(["/intake"]);
});
