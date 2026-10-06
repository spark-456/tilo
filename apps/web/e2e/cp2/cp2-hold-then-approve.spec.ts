// @cp2 SYS (FR-HIL-03, SEC-05): the web app against the real dev API, not fixtures. A held gate sends
// nothing and the run keeps waiting; approving it later completes the run and delivers. Every claim is
// what the API recorded (HR-1): the Needs-you count, the gate sheet's state and the delivery page.
import { expect, test } from "@playwright/test";
import { startRun, watchConsole } from "../support/cp2";
import { DESKTOP } from "../support/viewports";

test.describe("@cp2 hold then approve on the real dev API", () => {
  test("FR-HIL-03 SYS: Hold sends nothing and the gate stays open; a later Approve delivers", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    const world = await startRun(page);
    await expect(page.getByTestId("needs-count")).toHaveText("1", { timeout: 30_000 });

    await page.getByRole("link", { name: "Open the queue" }).click();
    await page.getByRole("link", { name: /^Review the gate/ }).click();
    const sheet = page.getByTestId("gate-sheet");
    await expect(sheet).toHaveAttribute("data-gate-state", "waiting");

    await sheet.getByRole("radio", { name: "Hold" }).check();
    await sheet.getByRole("button", { name: "Hold" }).click();
    await page.waitForTimeout(2000); // nothing to wait for: the point is that nothing happens
    await expect(sheet).toHaveAttribute("data-gate-state", "waiting");
    await page.getByRole("link", { name: "World", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/world/${world}$`));
    await expect(page.getByTestId("hud-meter")).toContainText("Working");
    await expect(page.getByTestId("needs-count")).toHaveText("1");

    await page.getByRole("link", { name: "Open the queue" }).click();
    await page.getByRole("link", { name: /^Review the gate/ }).click();
    await sheet.getByRole("radio", { name: "Approve" }).check();
    await sheet.getByRole("button", { name: "Approve" }).click();
    await expect(sheet).toHaveAttribute("data-gate-state", "decided", { timeout: 30_000 });
    await page.getByRole("link", { name: "World", exact: true }).first().click();
    await expect(page.getByTestId("hud-meter")).toContainText("Done", { timeout: 30_000 });
    expect(problems).toEqual([]);
  });
});
