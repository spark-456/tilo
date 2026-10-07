// WEB-CUTOVER: "/" is the Park Home, whose composer is not wired to the intake yet (plan WEB-13), and S-02
// and S-03 hold the brief the intake returned in the session ("Tilo has no brief for this task" without
// it). So the only way to open S-02 with a brief is S-01's form, whose body the old app still renders on an
// address no screen owns. `INTAKE_PATH` is such an address. When WEB-13 wires the Park composer to the
// intake, this helper opens the Home and uses that composer instead, and nothing else in the specs changes.
import { type Page, expect } from "@playwright/test";

export const INTAKE_PATH = "/start";

/** Opens the intake form (S-01's body), types `text`, starts the task and waits for S-02. */
export async function startTask(page: Page, text: string, search = ""): Promise<void> {
  await page.goto(`${INTAKE_PATH}${search}`);
  await page.getByLabel("Describe your task").fill(text);
  await page.getByRole("button", { name: "Start task", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
}
