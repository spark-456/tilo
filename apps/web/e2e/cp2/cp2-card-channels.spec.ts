// @cp2 FR-CHN-01 / FR-HIL-11 (PRD 10.3): one card, answered on one surface, closes on the other.
// Two browser contexts (a phone at 390x844 and a desktop at 1440x900) open the same waiting gate of
// one run on the real dev API (fake Director and runner, in-memory store, no credentials). The gate
// is answered on the phone; the desktop's gate sheet and queue follow the recorded approval.resolved
// within 2 s (HR-1: nothing closes until the event is on record), and that event names the channel
// the answer came from, "mobile_web". Run with `just e2e-cp2`.
import { expect, test } from "@playwright/test";
import { startRun, watchConsole } from "../support/cp2";
import { DESKTOP, MOBILE } from "../support/viewports";

const API = "http://127.0.0.1:8080";
const ORIGIN = `http://127.0.0.1:${process.env.TILO_CP2_PORT ?? 5391}`;

test.describe("@cp2 FR-CHN-01 FR-HIL-11 one card on two surfaces", () => {
  test("FR_HIL_11 a gate answered on mobile web closes on desktop web within 2 s, on the recorded event", async ({
    browser,
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    const world = await startRun(page);
    await expect(page.getByTestId("needs-count")).toHaveText("1", { timeout: 30_000 });
    await page.getByRole("link", { name: "Open the queue" }).click();
    await expect(page.getByTestId("needs-queue")).toBeVisible();
    const gate = await page.getByRole("link", { name: /^Review the gate/ }).getAttribute("href");
    expect(gate).toContain(`world=${world}`);

    // Desktop: the queue (this page) and the gate sheet (a second page of the same context).
    const desktopSheet = await page.context().newPage();
    watchConsole(desktopSheet);
    await desktopSheet.goto(gate ?? "");
    const desktop = desktopSheet.getByTestId("gate-sheet");
    await expect(desktop).toHaveAttribute("data-gate-state", "waiting");

    // Mobile: its own context, the same gate.
    const phone = await browser.newContext({ viewport: MOBILE, baseURL: ORIGIN });
    try {
      const mobilePage = await phone.newPage();
      problems.push(...watchConsole(mobilePage));
      await mobilePage.goto(gate ?? "");
      const mobile = mobilePage.getByTestId("gate-sheet");
      await expect(mobile).toHaveAttribute("data-gate-state", "waiting");
      await expect(mobile).toContainText("dev.recipient@example.com"); // the same card, in full
      await expect(desktop).toContainText("dev.recipient@example.com");

      await mobile.getByRole("radio", { name: "Approve" }).check();
      const sentAt = Date.now();
      await mobile.getByRole("button", { name: "Approve" }).click();
      await expect(desktop).toHaveAttribute("data-gate-state", "decided", { timeout: 2000 });
      expect(Date.now() - sentAt).toBeLessThanOrEqual(2000);
      await expect(desktop).toHaveAttribute("data-opened-by", "person");
      await expect(page.getByTestId("needs-empty")).toBeVisible({ timeout: 2000 }); // the queue row is gone
      await expect(mobile).toHaveAttribute("data-gate-state", "decided", { timeout: 2000 });

      // The recorded event says where the answer came from.
      const body = await (await mobilePage.request.get(`${API}/worlds/${world}/events`)).json();
      const resolved = (body.events as { type: string; data: { channel?: string } }[]).filter(
        (e) => e.type === "approval.resolved",
      );
      expect(resolved.map((e) => e.data.channel)).toEqual(["mobile_web"]);
    } finally {
      await phone.close();
    }
    expect(problems).toEqual([]);
  });
});
