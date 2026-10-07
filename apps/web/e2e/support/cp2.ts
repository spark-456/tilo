// Shared by the @cp2 specs (real dev API): console watch and the S-01 to S-03 walk.
import { type Page, expect } from "@playwright/test";
import { INTAKE_PATH } from "./intake";

export const TASK = "Draft a reply to the supplier email about the late delivery";
const CAP = "30";

/** Console errors and warnings and uncaught page errors, until the test ends. */
export function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") problems.push(msg.text());
  });
  return problems;
}

/** S-01 to S-03 on the real API; returns the run's world id once S-04 is open. WEB-CUTOVER: S-01's form is
 * opened at INTAKE_PATH (support/intake.ts), "/" is the Park Home. */
export async function startRun(page: Page): Promise<string> {
  await page.goto(INTAKE_PATH);
  await expect(page.getByTestId("fixture-replay-banner")).toHaveCount(0); // a real client
  await page.getByLabel("Describe your task").fill(TASK);
  await page.getByRole("button", { name: "Start task" }).click();

  // S-02: the Director's brief and questions; each is answered with its first suggestion
  await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
  const questions = page.getByTestId("question-item");
  await expect(questions.first()).toBeVisible();
  for (let i = 0; i < (await questions.count()); i++) {
    await questions.nth(i).locator("button.suggestion-btn").first().click();
  }
  await page.getByRole("button", { name: "Continue" }).click();

  // S-03: balanced approach, cap 30
  await expect(page.getByRole("heading", { level: 1, name: "Approaches" })).toBeVisible();
  await page.getByRole("button", { name: /^Balanced review/ }).click();
  await page.getByTestId("budget-cap-input").fill(CAP);
  await page.getByRole("button", { name: "Start this approach" }).click();

  await expect(page).toHaveURL(/\/world\/[^/]+\/stage$/);
  return new URL(page.url()).pathname.split("/").slice(-2)[0] ?? "";
}
