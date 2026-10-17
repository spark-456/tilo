import { act } from "react";
// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { q } from "../../../../test-support/park/componentsHarness";
import { typeInto } from "../../../../test-support/park/skillsHarness";
import { createLiveApi } from "../../api/liveApi";

vi.mock("../../../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  appCheckToken: undefined,
  authToken: undefined,
  sessionView: { demo: () => false, identity: () => null },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const plate = {
  today: "2026-10-17",
  as_of: "2026-10-17T03:00:00Z",
  truncated: false,
  rows: [],
  parked: [],
};

it("AGENDA_BOARDS_live_plate_keeps_both_cork_boards_and_routes_each_add_to_its_scope", async () => {
  const writes: { body: string; headers: Headers }[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (path === "/v1/plate") return new Response(JSON.stringify(plate));
    if (path === "/v1/people")
      return new Response(
        JSON.stringify({
          you: "ps_ari",
          people: [{ id: "ps_ari", display_name: "Ari", memberships: [{ team: "tm_launch" }] }],
        }),
      );
    if (path === "/v1/pinboards" && init?.method === "POST") {
      writes.push({ body: String(init.body), headers: new Headers(init.headers) });
      return new Response(JSON.stringify({ id: `pb_pin${writes.length}` }), { status: 201 });
    }
    if (path === "/v1/pinboards")
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "pb_mine",
              title: "Read the brief",
              body: "Before the planning call",
              status: "active",
              created_at: "2026-10-16T12:00:00Z",
              scope: { kind: "personal", user: "ps_ari" },
            },
            {
              id: "pb_team",
              title: "Review launch checklist",
              body: null,
              status: "active",
              created_at: "2026-10-16T12:00:00Z",
              scope: { kind: "team", team: "tm_launch" },
            },
          ],
          truncated: false,
        }),
      );
    if (path === "/v1/meetings")
      return new Response(JSON.stringify({ items: [], truncated: false }));
    if (path === "/v1/connectors") return new Response(JSON.stringify({ connectors: [] }));
    return new Response(JSON.stringify({ cards: [], next_cursor: null }));
  });
  vi.stubGlobal("fetch", fetcher);
  const api = createLiveApi({ baseUrl: "https://api.example.test", fetch: fetcher });
  const { container } = await renderAgenda({ api });

  const myBoard = container.querySelector<HTMLElement>('[aria-label="My board"]');
  const teamBoard = container.querySelector<HTMLElement>('[aria-label="Team board"]');
  expect(myBoard).not.toBeNull();
  expect(teamBoard).not.toBeNull();
  expect(myBoard?.querySelector("[data-cork-board]")).not.toBeNull();
  expect(teamBoard?.querySelector("[data-cork-board]")).not.toBeNull();
  expect(myBoard?.textContent).toContain("Read the brief");
  expect(teamBoard?.textContent).toContain("Review launch checklist");
  expect(container.textContent).toContain("Tilo suggests");
  expect(container.textContent).toContain("Event details");
  expect(container.querySelector('[aria-label="Week calendar"]')).not.toBeNull();
  if (!myBoard || !teamBoard) throw new Error("Both boards should render");

  typeInto(q(myBoard, 'input[aria-label="Pin to My board"]'), "Personal note");
  typeInto(q(teamBoard, 'input[aria-label="Pin to Team board"]'), "Team note");
  const addPin = (board: HTMLElement) => q<HTMLButtonElement>(board, 'button[type="submit"]');
  act(() => {
    addPin(myBoard).click();
    addPin(teamBoard).click();
  });
  await settle();

  expect(writes.map((write) => JSON.parse(write.body))).toEqual([
    { title: "Personal note" },
    { title: "Team note", team: "tm_launch" },
  ]);
  expect(writes.every((write) => write.headers.get("Idempotency-Key"))).toBe(true);
});
