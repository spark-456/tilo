// Shared by the per-screen smoke specs (AGW-08, PRD 18.3).
import { type Page, expect } from "@playwright/test";

/** Console errors and warnings, and uncaught page errors, collected until the test ends. */
export function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") problems.push(msg.text());
  });
  return problems;
}

/** Every button on the screen is a placeholder (aria-disabled or disabled): never a dead click. */
export async function expectNoDeadControls(page: Page, scope = "main") {
  const buttons = page.locator(`${scope} button`);
  for (let i = 0; i < (await buttons.count()); i++) {
    const b = buttons.nth(i);
    const disabled = (await b.getAttribute("aria-disabled")) === "true" || (await b.isDisabled());
    expect(disabled, `button "${await b.innerText()}" is neither disabled nor a link`).toBe(true);
  }
}
