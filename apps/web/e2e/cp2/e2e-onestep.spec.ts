// E2E-ONESTEP: the whole signed-in journey on the real dev API (fake Director and fake runner, no credentials, no paid
// call; `just e2e-cp2`, project "cp2"): Home, type a task, the one confirm card, Start, the World builds from recorded
// events, a Needs-you card, the answer, the run finishes, the result, "Open result"; then Skills, Team, Agenda and
// Connectors. Every step is held to: no console error and no request answered 400 or more (a 304 and a closed
// stream are no failure).
import { appendFileSync } from "node:fs";
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP } from "../support/viewports";

interface Watch {
  problems: string[];
  failed: string[];
}

function watch(page: Page): Watch {
  const w: Watch = { problems: [], failed: [] };
  page.on("pageerror", (err) => {
    w.problems.push(`pageerror: ${err.message}`);
    note(`pageerror ${err.message}`);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      w.problems.push(`${msg.type()}: ${msg.text()}`);
      note(`console ${msg.type()} ${msg.text().slice(0, 200)}`);
    }
  });
  page.on("response", (res) => {
    if (res.status() >= 400) {
      w.failed.push(`${res.status()} ${res.request().method()} ${res.url()}`);
      note(`HTTP ${res.status()} ${res.request().method()} ${res.url()}`);
    }
  });
  return w;
}

const LOG = process.env.ONESTEP_LOG;
const note = (line: string) => {
  if (LOG)
    appendFileSync(
      LOG,
      `${new Date().toISOString().slice(11, 19)} ${line}
`,
    );
};

const clean = (w: Watch, where: string) => {
  expect(w.failed, `${where}: requests answered 400 or more`).toEqual([]);
  expect(w.problems, `${where}: console errors`).toEqual([]);
};

/** One named step of the journey; a break is written down with the page's words before it is rethrown. */
async function step(page: Page, name: string, body: () => Promise<void>): Promise<void> {
  note(`step ${name}`);
  try {
    await body();
    note(`ok   ${name}`);
  } catch (error) {
    const text = await page
      .locator("body")
      .innerText({ timeout: 3000 })
      .catch(() => "(no page text)");
    note(`FAIL ${name} at ${page.url()}: ${String(error).slice(0, 300)}`);
    note(`page: ${text.replace(/\s+/g, " ").slice(0, 600)}`);
    throw error;
  }
}

test.describe("@cp2 CX-UX-JOURNEY-E2E the judge journey", () => {
  test("CX_UX_JOURNEY_E2E fixture sign-in, Home run, approval, result and key pages stay console-clean", async ({
    page,
  }) => {
    test.setTimeout(200_000);
    await page.setViewportSize(DESKTOP);
    const w = watch(page);
    // The dev API has no generated brief for its fixture owner. Keep the smoke fixture in its empty state without
    // treating the API's intentional `not_ready` 404 as a journey failure.
    await page.route("**/v1/me/brief", (route) => {
      if (route.request().method() !== "GET") return route.continue();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          v: "1.0",
          owner: "fixture-owner",
          local_date: "2026-10-17",
          time_zone: "Asia/Kolkata",
          generated_at: "2026-10-17T00:00:00+05:30",
          trigger: "schedule",
          model: "skipped",
          meetings: { status: "not_connected", items: [] },
          mail_needing_reply: { status: "not_connected", items: [] },
          deadlines: { status: "ok", items: [] },
          suggestions: [],
          todo_suggestions: [],
        }),
      });
    });
    // The result route fails closed for the dev runner's unscreened outputs. Use a fake result only in this UI smoke.
    await page.route("**/worlds/*/result*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/markdown; charset=utf-8",
        headers: { "content-disposition": 'attachment; filename="tilo-result.md"' },
        body: "# Supplier comparison\n\nThe three supplier quotes are ready to review.",
      }),
    );

    await step(page, "fixture sign-in", async () => {
      // CP2 installs one in-memory owner principal and fake providers; no Firebase or paid call.
      const api = `http://127.0.0.1:${process.env.TILO_CP2_API_PORT ?? 8080}`;
      expect((await page.request.get(`${api}/v1/me/settings`)).status()).toBe(200);
    });

    await step(page, "Home: type a task, one confirm card, Start", async () => {
      await page.goto("/");
      const box = page.getByLabel("Describe your task");
      await expect
        .poll(
          async () =>
            (await box.count()) > 0 ||
            (await page.getByText("Home data is unavailable").count()) > 0,
          { timeout: 30_000 },
        )
        .toBe(true);
      if (await page.getByText("Home data is unavailable").isVisible()) {
        throw new Error(
          `Home reads failed: ${JSON.stringify(w.failed)}; ${JSON.stringify(w.problems)}`,
        );
      }
      await expect(box).toBeVisible({ timeout: 30_000 });
      await box.fill("Compare three suppliers' quotes and recommend one.");
      await page.getByRole("button", { name: "Start task" }).click();
      const card = page.getByTestId("run-card");
      await expect(card).toBeVisible({ timeout: 40_000 });
      await card.getByRole("button", { name: "Start", exact: true }).click();
      await expect(page).toHaveURL(/\/world\/w_/, { timeout: 40_000 });
    });
    const worldId = new URL(page.url()).pathname.split("/")[2] as string;
    note(`world ${worldId}`);

    await step(page, "World builds from recorded events", async () => {
      await expect(page.getByTestId("pending-world")).toContainText("Tilo is planning your world");
      const api = `http://127.0.0.1:${process.env.TILO_CP2_API_PORT ?? 8080}`;
      await expect
        .poll(
          async () => {
            const response = await page.request.get(`${api}/worlds/${worldId}/events`);
            const body = (await response.json()) as { events: { type: string }[] };
            return body.events.map((event) => event.type);
          },
          { timeout: 60_000 },
        )
        .toContain("world.planned");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("region", { name: "Live run" })).toContainText(
        "recorded events",
        {
          timeout: 30_000,
        },
      );
    });

    await step(page, "Needs-you card", async () => {
      await page.goto(`/needs-you?world=${worldId}`);
      const queue = page.getByTestId("needs-queue");
      await expect(queue.locator("li").first()).toBeVisible({ timeout: 60_000 });
    });

    await step(page, "answer it: the gate opens only on the person's answer", async () => {
      const queue = page.getByTestId("needs-queue");
      const review = queue.getByRole("link", { name: /^Review the gate/ });
      if ((await review.count()) > 0) await review.first().click();
      else
        await queue
          .getByRole("button", { name: /^Answer/ })
          .first()
          .click();
      const group = page.getByRole("radiogroup", { name: "Your options" });
      await expect(group).toBeVisible({ timeout: 20_000 });
      await group.getByRole("radio", { name: /approve|yes|go on/i }).check();
      await page.locator(".need-actions button.primary").first().click();
      await expect(page.locator(".need-status, .gate-status").first()).toBeVisible({
        timeout: 20_000,
      });
    });

    await step(page, "the run continues and finishes", async () => {
      await page.goto(`/world/${worldId}/delivery`);
      await expect(page.getByTestId("delivery")).toContainText("Finished", { timeout: 90_000 });
    });

    await step(
      page,
      "the world holds what happened: agents, buildings, Story and Trace",
      async () => {
        await page.goto(`/world/${worldId}`);
        const status = page.getByTestId("run-status");
        await expect(status).toContainText("Done", { timeout: 30_000 });
        const meta = page.locator(".park-world-meta");
        await expect(meta).toContainText(/\d+ agents/);
        await expect(meta).not.toContainText(/Owned by\s*·|\dT\d\d:|(^|\s)0 agents/);
        await expect(meta).toContainText(/started \d{1,2} [A-Z][a-z]{2}/);
        await page.goto(`/world/${worldId}/story`);
        await expect(page.getByTestId("story-lens").locator("li").first()).toBeVisible({
          timeout: 20_000,
        });
        await page.goto(`/world/${worldId}/trace`);
        await expect(page.getByTestId("trace-lens-row").first()).toBeVisible({ timeout: 20_000 });
      },
    );

    await step(
      page,
      "result: the output is readable on the page, Open and Download work",
      async () => {
        // WORLD-USEFUL: the page reads the delivered output itself as soon as the run is recorded as done
        const read = page.waitForResponse((r) => r.url().includes(`/worlds/${worldId}/result`), {
          timeout: 30_000,
        });
        await page.goto(`/world/${worldId}`);
        expect((await read).status(), "GET /worlds/{id}/result").toBe(200);
        await expect(page.getByTestId("run-status")).toContainText("Done");
        const result = page.getByTestId("run-result");
        await expect(result.getByTestId("result-text")).toBeVisible({ timeout: 30_000 });
        const open = result.getByRole("button", { name: "Open result" });
        await expect(open).toBeVisible();
        await expect(open).not.toHaveAttribute("aria-disabled", "true");
        const [download] = await Promise.all([
          page.waitForEvent("download", { timeout: 20_000 }),
          result.getByRole("button", { name: "Download", exact: true }).click(),
        ]);
        expect(download.suggestedFilename()).toMatch(/^tilo-result-/);
      },
    );

    for (const [name, path, heading] of [
      ["Agenda", "/agenda", /agenda/i],
      ["Skills", "/skills", /skills/i],
      ["Connectors", "/connectors", /connect/i],
    ] as const) {
      await step(page, `${name} loads`, async () => {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible({
          timeout: 30_000,
        });
        await page.waitForTimeout(1500); // the page's own reads settle
      });
    }

    clean(w, "journey");
  });
});
