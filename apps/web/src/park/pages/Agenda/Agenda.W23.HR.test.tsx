// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";

afterEach(cleanup);

it("HR W23 sample Agenda booking explains no calendar action happened", async () => {
  const { container, toast } = await renderAgenda();
  expect(container.textContent).toContain(
    "Sample week: no meetings are booked, invitations sent or reminders scheduled.",
  );
  const find = qa<HTMLButtonElement>(container, "button").find((b) =>
    b.textContent?.includes("Find a time"),
  );
  expect(find).toBeTruthy();
  if (!find) throw new Error("Find a time missing");
  click(find);
  click(q(container, "[data-slot]"));
  await settle();
  expect(toast()).toBe(
    "Sample booking for Thu 16:00 shown on this page only. No meeting was booked or invitations sent.",
  );
});
