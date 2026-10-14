// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, renderAgenda } from "../../../../test-support/park/agendaHarness";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
it("PE_26 W2 no person record shows empty Agenda work without a load error", async () => {
  const { container } = await mount({ detail: "Not Found" }, 404);
  expect(container.textContent).toContain("Nothing on your plate");
  expect(container.textContent).not.toMatch(/The Agenda could not load|Prepare notes|2026-10-09/);
});
const body = {
  today: "2026-10-09",
  as_of: "2026-10-09T03:00:00Z",
  truncated: false,
  rows: [
    {
      ref: { kind: "pin", id: "pin-a" },
      title: "Prepare notes",
      at: null,
      due: "2026-10-10",
      from: null,
      group: "soon",
    },
  ],
  parked: [],
};
const mount = (reply: unknown = body, status = 200) =>
  renderAgenda({
    api: createLiveApi({
      baseUrl: "https://api.example.test",
      fetch: async (input) =>
        new Response(
          JSON.stringify(
            String(input).endsWith("/v1/plate") ? reply : { cards: [], next_cursor: null },
          ),
          { status },
        ),
    }),
  });
it("FR_UX_14 FR_PB live Agenda shows supplied work and honest unavailable panels", async () => {
  const { container } = await mount();
  expect(container.querySelector('[data-source="live"]')).not.toBeNull();
  expect(container.textContent).toContain("Prepare notes");
  expect(container.textContent).toContain("2026-10-10");
  for (const label of ["Week view", "Event details", "Available times", "Boards"]) {
    expect(container.querySelector(`[aria-label="${label}"]`)?.textContent).toContain(
      "Not available yet",
    );
  }
  expect(container.textContent).not.toContain("synced just now");
  expect(container.querySelector("button")).toBeNull();
});
it("FR_PB empty live plate shows empty work without fabricating a week", async () => {
  const { container } = await mount({ ...body, rows: [] });
  expect(container.textContent).toContain("Nothing on your plate");
  expect(container.querySelector('[aria-label="Week view"]')?.textContent).toContain(
    "Not available yet",
  );
});
it("FR_UX_14 a failed plate read shows the existing error instead of sample pins", async () => {
  const { container } = await mount({}, 503);
  expect(container.textContent).toContain("The Agenda could not load");
  expect(container.textContent).not.toContain("Prepare notes");
});
it("FR_PB calendar summaries and parked work retain supplied facts and truncation", async () => {
  const { container } = await mount({
    ...body,
    truncated: true,
    rows: [
      {
        ...body.rows[0],
        ref: { kind: "calendar_entry", id: "entry-a" },
        title: "Design review",
        at: "2026-10-09T05:00:00Z",
      },
    ],
    parked: [{ ...body.rows[0], ref: { kind: "work_item", id: "work-a" }, title: null }],
  });
  const calendar = container.querySelector('[aria-label="Today\'s calendar"]');
  expect(calendar?.textContent).toContain("Design review");
  expect(calendar?.querySelector('time[datetime="2026-10-09T05:00:00Z"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Parked work"]')?.textContent).toContain(
    "Untitled item",
  );
  expect(container.textContent).toContain("Showing a limited list.");
  expect(container.querySelector('[aria-label="Event details"]')?.textContent).toContain(
    "Not available yet",
  );
});
