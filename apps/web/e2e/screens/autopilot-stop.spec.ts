// FR-HIL-07 S-15 Stop all autopilot on the fixture client: it asks first with nothing chosen, a
// second deliberate press sends it, and the page says what the answer says and nothing before it.
// The fixture holds no rule that runs on its own, so its honest answer is "nothing needed stopping".
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

for (const [name, viewport] of [
  ["1440x900", DESKTOP],
  ["390x844", MOBILE],
] as const) {
  test(`FR_HIL_07 S-15 asks, then sends, then reports the API's answer at ${name}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      const w = window as unknown as { __cls: number };
      w.__cls = 0;
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
          if (!s.hadRecentInput) w.__cls += s.value;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/autonomy?speed=100");
    const root = page.getByTestId("stop-autopilot");
    await expect(root).toHaveAttribute("data-stop", "ready", { timeout: 20_000 });
    await expect(page.getByTestId("stop-result")).toHaveText(""); // nothing claimed up front

    // 1. Asking sends nothing and chooses nothing.
    await root.getByRole("button", { name: "Stop all autopilot" }).click();
    await expect(root).toHaveAttribute("data-stop", "confirming");
    await expect(root.getByRole("heading", { name: "Stop all autopilot?" })).toBeFocused();
    await expect(page.getByTestId("stop-result")).toHaveText("");

    // 2. Cancel puts the control back, with focus on it.
    await root.getByRole("button", { name: "Keep autopilot as it is" }).click();
    await expect(root).toHaveAttribute("data-stop", "ready");
    await expect(root.getByRole("button", { name: "Stop all autopilot" })).toBeFocused();

    // 3. The second, deliberate press sends it; the words come from the answer.
    await root.getByRole("button", { name: "Stop all autopilot" }).click();
    await root.getByRole("button", { name: "Stop all autopilot" }).click();
    await expect(root).toHaveAttribute("data-stop", "done");
    await expect(page.getByTestId("stop-result")).toContainText(
      "No rule was running on its own, so nothing needed stopping.",
    );
    await expect(page.getByTestId("stop-result")).not.toContainText("Stopped");

    expect(await page.evaluate(() => (window as unknown as { __cls: number }).__cls)).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width,
    );
    expect(problems).toEqual([]);
  });
}
