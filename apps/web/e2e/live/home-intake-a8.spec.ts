// A8 / FR-INT-01..04 / NFR-22 (14 Oct, "the first live Home task must work flawlessly"): the signed-in Home task
// flow against the LIVE Api seam, with POST /intake answered by `page.route` mocks: no network, no sign-in, no
// paid call. Response shapes follow services/api/src/tilo_api/intake.py (201 {task_id, brief, questions, files};
// refusals as FastAPI `{detail}`) and contracts/brief.schema.json. Each case checks what the person sees and that
// nothing is started that the server did not accept (HR-1).
// Local only (TILO_LIVE=1): TILO_LIVE=1 TILO_LIVE_PORT=<own> TILO_LIVE_API_PORT=<own> pnpm --filter @tilo/web
// exec playwright test e2e/live/home-intake-a8 --project=live --workers=1
import { type Page, type Route, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "content-type": "application/json",
};
const BRIEF = {
  goal: "Compare three suppliers and recommend one.",
  deliverables: [{ title: "Supplier comparison", format: "pdf" }],
  audience: "Operations lead",
  deadline: null,
  constraints: [],
  sources: [],
  sensitivity: "business",
  assumptions: [],
  applied_preferences: [],
};
const CREATED = { task_id: "t_a8_1", brief: BRIEF, questions: [], files: [] };

interface Reply {
  status: number;
  body?: unknown;
  /** Held this long before answering (ms). */
  delay?: number;
  /** Never answered (the connection hangs). */
  hang?: boolean;
}

interface Mock {
  posts: () => number;
  keys: () => string[];
  bodies: () => string[];
}

/** Answers POST /intake from `replies` in order (the last one repeats) and records what arrived. */
async function mockIntake(page: Page, replies: Reply[]): Promise<Mock> {
  const keys: string[] = [];
  const bodies: string[] = [];
  await page.route(`${API}/intake`, async (route: Route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.fulfill({ status: 204, headers: CORS });
    const n = keys.length;
    keys.push(req.headers()["idempotency-key"] ?? "");
    bodies.push(req.postData() ?? "");
    const r = replies[Math.min(n, replies.length - 1)] as Reply;
    if (r.hang) return; // never fulfilled
    if (r.delay) await new Promise((done) => setTimeout(done, r.delay));
    return route.fulfill({ status: r.status, headers: CORS, body: JSON.stringify(r.body ?? {}) });
  });
  return { posts: () => keys.length, keys: () => keys, bodies: () => bodies };
}

const input = (page: Page) => page.getByLabel("Describe your task");
const confirm = (page: Page) => page.getByRole("button", { name: "Start now" });
const status = (page: Page) => page.getByRole("status");

async function planFor(page: Page, text = "Compare three suppliers"): Promise<void> {
  await page.goto("/");
  await expect(input(page)).toBeVisible({ timeout: 60_000 });
  await input(page).fill(text);
  await page.getByRole("button", { name: "Start task", exact: true }).click();
  await expect(confirm(page)).toBeVisible();
}

const focusIsOnPage = (page: Page) =>
  page.evaluate(() => document.activeElement !== null && document.activeElement !== document.body);

test("A8_201_created_shows_a_busy_confirm_then_the_toast_with_Open_and_one_keyed_POST", async ({
  page,
}) => {
  const intake = await mockIntake(page, [{ status: 201, body: CREATED, delay: 800 }]);
  await planFor(page);
  await confirm(page).click();
  await expect(confirm(page)).toHaveAttribute("aria-busy", "true");
  await expect(confirm(page)).toBeDisabled();
  await expect.poll(intake.posts).toBe(1);
  expect(intake.keys()[0]).toMatch(/^[0-9a-f-]{16,}$/i);
  expect(intake.bodies()[0]).toContain("Compare three suppliers");

  const open = status(page).getByRole("button", { name: "Open", exact: true });
  await expect(open).toBeVisible();
  await expect(page.locator(".park-home-plan")).toHaveCount(0);
  await expect(input(page)).toHaveValue("");
  expect(await focusIsOnPage(page), "focus is not lost to the page body").toBe(true);
  await open.click();
  await expect(page).toHaveURL(/\/task\/t_a8_1\/understanding$/);
  expect(intake.posts()).toBe(1);
});

const REFUSALS: Array<{ name: string; reply: Reply; says: RegExp; not?: RegExp }> = [
  {
    name: "503_safety_screen_unavailable",
    reply: {
      status: 503,
      body: { detail: "The safety screen is unavailable; nothing was stored." },
    },
    says: /safety check/i,
  },
  {
    name: "503_not_configured",
    reply: { status: 503, body: { detail: "not_configured" } },
    says: /not set up|not connected/i,
    not: /not_configured/,
  },
  {
    name: "429_demo_runs_busy",
    reply: { status: 429, body: { detail: "demo_runs_busy" } },
    says: /busy|try again/i,
    not: /demo_runs_busy/,
  },
  {
    name: "402_limit_reached",
    reply: { status: 402, body: { detail: "cap_reached" } },
    says: /limit/i,
    not: /cap_reached/,
  },
  {
    name: "409_intake_already_committed",
    reply: { status: 409, body: { detail: { code: "intake_already_committed", task_id: "t_x" } } },
    says: /already submitted/i,
  },
];

for (const c of REFUSALS) {
  test(`A8_${c.name}_says_so_plainly_keeps_the_card_and_the_text_and_adds_nothing`, async ({
    page,
  }) => {
    const intake = await mockIntake(page, [c.reply]);
    await planFor(page);
    await confirm(page).click();
    await expect.poll(intake.posts).toBe(1);
    await expect(status(page).filter({ hasText: c.says })).toBeVisible();
    if (c.not) await expect(page.getByText(c.not)).toHaveCount(0);
    // nothing was started: no Open, the card and the typed text are still there, the confirm works again
    await expect(page.getByRole("button", { name: "Open", exact: true })).toHaveCount(0);
    await expect(confirm(page)).toBeEnabled();
    await expect(confirm(page)).not.toHaveAttribute("aria-busy", "true");
    await expect(input(page)).toHaveValue("Compare three suppliers");
    expect(await focusIsOnPage(page), "focus is not lost to the page body").toBe(true);
    expect(intake.posts(), "no automatic retry").toBe(1);
  });
}

test("A8_slow_reply_keeps_one_spinner_and_ignores_a_second_tap_Enter_and_Escape", async ({
  page,
}) => {
  const intake = await mockIntake(page, [{ status: 201, body: CREATED, delay: 2500 }]);
  await planFor(page);
  await confirm(page).click();
  await expect(confirm(page)).toHaveAttribute("aria-busy", "true");
  await confirm(page)
    .click({ force: true, timeout: 500 })
    .catch(() => undefined);
  await input(page).press("Enter");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await expect(
    page.locator(".park-home-plan"),
    "Escape does not close a card mid-send",
  ).toHaveCount(1);
  expect(intake.posts(), "one POST").toBe(1);
  await expect(status(page).getByRole("button", { name: "Open", exact: true })).toBeVisible({
    timeout: 10_000,
  });
  expect(intake.posts()).toBe(1);
});

test("A8_offline_says_unreachable_keeps_the_text_and_a_retry_after_reconnecting_works", async ({
  page,
  context,
}) => {
  const intake = await mockIntake(page, [{ status: 201, body: CREATED }]);
  await planFor(page);
  await context.setOffline(true);
  await confirm(page).click();
  await expect(status(page).filter({ hasText: /could not be reached|connection/i })).toBeVisible();
  await expect(input(page)).toHaveValue("Compare three suppliers");
  await expect(confirm(page)).toBeEnabled();
  expect(intake.posts(), "the offline request never reached the mock").toBe(0);
  await context.setOffline(false);
  await confirm(page).click();
  await expect(status(page).getByRole("button", { name: "Open", exact: true })).toBeVisible();
  expect(intake.posts()).toBe(1);
});

test("A8_a_reply_that_never_comes_ends_in_a_plain_message_not_a_stuck_spinner", async ({
  page,
}) => {
  await page.clock.install();
  const intake = await mockIntake(page, [{ status: 201, hang: true }]);
  await planFor(page);
  await confirm(page).click();
  await expect.poll(intake.posts).toBe(1);
  await expect(confirm(page)).toHaveAttribute("aria-busy", "true");
  await page.clock.fastForward(180_000);
  await expect(
    status(page).filter({ hasText: /took too long|no answer|taking too long/i }),
  ).toBeVisible();
  await expect(confirm(page)).toBeEnabled();
  await expect(input(page)).toHaveValue("Compare three suppliers");
});
