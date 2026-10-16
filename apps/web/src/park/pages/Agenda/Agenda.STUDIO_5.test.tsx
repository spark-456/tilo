// @vitest-environment happy-dom
// UI-STUDIO-5 Agenda (design/studio-v2 "Tilo S Agenda"): the live Agenda lays today's calendar, the plate, the
// meetings and parked work from the live plate. Sections without data are hidden.
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

it("STUDIO_5 agenda live: today and the recorded plate", async () => {
  const { container } = await mount();
  expect(container.textContent).toContain(
    "Tilo prepares a brief before each meeting and takes notes in the ones you invite it to.",
  );
  const main = container.querySelector(".park-agenda-studiomain");
  expect(main?.querySelector('[aria-label="Today\'s calendar"]')?.textContent).toContain(
    "Supplier call",
  );
  expect(main?.querySelector('[aria-label="Your plate"]')?.textContent).toContain("Send the quote");
  expect(container.querySelector(".park-agenda-studioside")).toBeNull();
});

it("STUDIO_5 agenda live: no invented brief, suggestion or button without a read behind it", async () => {
  const { container } = await mount();
  expect(container.textContent).not.toContain("Not available yet");
  expect(container.querySelector("button")).toBeNull();
  expect(container.textContent).not.toMatch(/Voltway|Add to calendar|Dismiss|Open the full brief/);
});
