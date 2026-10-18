// @vitest-environment happy-dom
// UI-STUDIO-5 Agenda (design/studio-v2 "Tilo S Agenda"): the live Agenda lays today's calendar, the plate, the
// meetings and parked work from the live plate. Empty week structures remain visible.
import { act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
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
  // P0-AGENDA-REDO replaces the old Today list with a navigable month grid.
  act(() =>
    container.querySelector<HTMLButtonElement>(".cx-agenda-views button:nth-child(3)")?.click(),
  );
  await settle();
  const month = container.querySelector<HTMLElement>('[aria-label="Month calendar"]');
  expect(month?.hidden).toBe(false);
  expect(container.querySelector<HTMLElement>('[aria-label="Week time slots"]')?.hidden).toBe(true);
  expect(month?.textContent).toContain("Supplier call");
  const main = container.querySelector(".park-agenda-studiomain");
  expect(main?.querySelector('[aria-label="Your plate"]')?.textContent).toContain("Send the quote");
  expect(container.querySelector('[aria-label="Week calendar"]')).not.toBeNull();
  expect(container.querySelector(".park-agenda-studioside")).not.toBeNull();
});

it("STUDIO_5 agenda live: honest empty structures have no invented data", async () => {
  const { container } = await mount();
  expect(container.textContent).not.toContain("Not available yet");
  expect(container.querySelector('[aria-label="Available times"]')?.textContent).toContain(
    "Suggested times",
  );
  // AGENDA-BOARDS (owner, 17 Oct): the boards are permanent furniture, named My board and Team board.
  const boards = container.querySelector('[aria-label="Boards"]')?.textContent;
  expect(boards).toContain("My board");
  expect(boards).toContain("Team board");
  expect(container.textContent).not.toMatch(/Voltway|Add to calendar|Dismiss|Open the full brief/);
});
