import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { noLayoutShift, soon, visit } from "../support/screens-b";

test("S_09 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  const problems = watchConsole(page);
  await visit(page, "/meeting", "Meeting", async () => {
    await expect(page.getByText("No meeting has been recorded in this run.")).toBeVisible();
    await soon(page, "Decline audio");
    await soon(page, "Add note");
    await soon(page, "Join meeting");
  });
  expect(problems).toEqual([]);
});

noLayoutShift([
  ["S_09", "/meeting?client_delay_ms=3000", "No meeting has been recorded in this run."],
]);
