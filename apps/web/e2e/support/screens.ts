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

/** Every button on the screen is a placeholder (aria-disabled or disabled): never a dead click.
 * The one filled primary button navigates, and each screen's own test clicks it. A lens control
 * (data-lens-control, FR-WLD-06) selects an object and is covered by lens-sync.spec.ts; Pause all
 * (data-pause-control, FR-WLD-07) sends a request and is covered by world-pause.spec.ts; Stop all
 * autopilot (data-stop-control, FR-HIL-07) asks first and is covered by autopilot-stop.spec.ts. The
 * Ask Tilo launcher (data-assistant-control, FR-PA-12) opens the assistant panel and is covered by
 * assistant-panel.spec.ts. The S-14 phone Filters button (data-filter-control) opens the size
 * chips and is covered by worlds-list.spec.ts. */
export async function expectNoDeadControls(page: Page, scope = "main") {
  const buttons = page.locator(
    `${scope} button:not(.primary):not(.park-btn--primary):not([data-lens-control]):not([data-pause-control]):not([data-stop-control]):not([data-assistant-control]):not([data-filter-control])`,
  );
  for (let i = 0; i < (await buttons.count()); i++) {
    const b = buttons.nth(i);
    const disabled = (await b.getAttribute("aria-disabled")) === "true" || (await b.isDisabled());
    expect(disabled, `button "${await b.innerText()}" is neither disabled nor a link`).toBe(true);
  }
}
