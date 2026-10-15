// @vitest-environment happy-dom
// UI-STUDIO-5 Agenda (design/studio-v2 "Tilo S Agenda"): the live Agenda lays today's calendar, the plate, the
// meetings and parked work on the left and Tilo's brief and suggestions on the right. Only what GET /v1/plate sends
// is shown; the brief and the suggestions have no read yet, so they say so and offer no action.
import { afterEach, expect, it } from "vitest";
import { cleanup, renderAgenda } from "../../../../test-support/park/agendaHarness";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
const plate = {
  today: "2026-10-15",
  as_of: "2026-10-15T03:00:00Z",
  truncated: false,
  rows: [
    {
      ref: { kind: "calendar_entry", id: "c1" },
      title: "Supplier call",
      at: "2026-10-15T05:30:00Z",
      due: null,
      from: null,
      group: "today",
    },
    {
      ref: { kind: "pin", id: "p1" },
      title: "Send the quote",
      at: null,
      due: "2026-10-16",
      from: null,
      group: "soon",
    },
  ],
  parked: [],
};
const mount = () =>
  renderAgenda({
    api: createLiveApi({
      baseUrl: "https://api.example.test",
      fetch: async (input) =>
        new Response(
          JSON.stringify(
            String(input).endsWith("/v1/plate") ? plate : { cards: [], next_cursor: null },
          ),
        ),
    }),
  });

it("MB_T2 STUDIO_5 agenda live keeps the brief promise manual until the sweep exists", async () => {
  const { container } = await mount();
  expect(container.textContent).toContain(
    "Ask Tilo for a brief when you need one. Tilo takes notes in meetings you invite it to.",
  );
  const main = container.querySelector(".park-agenda-studiomain");
  const side = container.querySelector(".park-agenda-studioside");
  expect(main?.querySelector('[aria-label="Today\'s calendar"]')?.textContent).toContain(
    "Supplier call",
  );
  expect(main?.querySelector('[aria-label="Your plate"]')?.textContent).toContain("Send the quote");
  expect(side?.querySelector('[aria-label="Event details"]')?.textContent).toContain(
    "Tilo’s brief",
  );
  expect(side?.querySelector('[aria-label="Event details"]')?.textContent).toContain(
    "When you ask Tilo for a brief",
  );
  expect(side?.querySelector('[aria-label="Available times"]')?.textContent).toContain(
    "Tilo suggests",
  );
});

it("STUDIO_5 agenda live: no invented brief, suggestion or button without a read behind it", async () => {
  const { container } = await mount();
  const side = container.querySelector(".park-agenda-studioside");
  for (const card of side?.querySelectorAll("section") ?? [])
    expect(card.textContent).toContain("Not available yet");
  expect(container.querySelector("button")).toBeNull();
  expect(container.textContent).not.toMatch(/Voltway|Add to calendar|Dismiss|Open the full brief/);
});
