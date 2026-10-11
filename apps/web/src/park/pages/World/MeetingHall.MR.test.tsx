// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { roomOf } from "../../api/live/meetingHall";
import { MeetingHall } from "./MeetingHall";

afterEach(cleanup);
const room = {
  room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  world_id: "w_one",
  run_id: "r_one",
  state: "open",
  reason: null,
  lead: "A_one",
  agents: ["A_two"],
  as_role: "owner",
  credit_cap: 5,
  credits_spent: 0,
  max_turns: 10,
  turns: [] as unknown[],
};
it("MR-01/MR-06 reads recorded attendees, convenes, asks, confirms and adjourns through the room routes", async () => {
  const calls: [string, unknown][] = [];
  let held: Omit<typeof room, "reason"> & { reason: string | null } = { ...room };
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace("https://api.test", "");
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push([path, body]);
    let value: unknown = held;
    if (path.endsWith("/layout"))
      value = {
        semantic: {
          levels: [{ districts: [{ id: "d1", lead: "A_one" }] }],
          agents: [
            { id: "A_one", rank: "lead" },
            { id: "A_two", rank: "writer" },
          ],
        },
      };
    if (path.includes("/events"))
      value = { events: [{ actor: "A_two", target: null, district: "d1" }], next_cursor: null };
    if (path.endsWith("/turns")) {
      const turn = {
        turn: 1,
        to: "A_one",
        mode: "quick",
        text: "Why?",
        reply: {
          from: "A_one",
          outcome: "proposed_change",
          text: "Revise the draft",
          units: ["U1"],
          artifacts: [],
          proposal: { proposal_id: "01ARZ3NDEKTSV4RRFFQ69G5FAW", units: ["U1"], artifacts: [] },
        },
        change: null,
      };
      held = { ...held, turns: [turn] };
      value = turn;
    }
    if (path.endsWith("/changes"))
      value = {
        proposal_id: "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        to: "A_one",
        units: ["U1"],
        artifacts: [],
        planning: "pending",
      };
    if (path.endsWith("/adjourn")) held = { ...held, state: "adjourned", reason: "person" };
    if (path.endsWith("/adjourn")) value = held;
    return new Response(JSON.stringify(value), { status: 200 });
  });
  await act(async () => {
    mount(
      <MeetingHall
        worldId="w_one"
        client={new HttpClient({ baseUrl: "https://api.test", fetch: fetcher })}
      />,
    );
  });
  expect(document.body.textContent).toContain("writer · A_two");
  await clickLabel("writer · A_two");
  await tap("Convene");
  expect(document.body.textContent).toContain("0 / 5 credits");
  await enter("Question", "Why?");
  await tap("Send question");
  expect(document.body.textContent).toContain("Revise the draft");
  await enter("Change wording", "Revise with sources");
  await tap("Confirm change");
  expect(document.body.textContent).toContain("Change recorded; planning pending.");
  await tap("Adjourn");
  expect(document.body.textContent).toContain("Adjourned · Closed by request");
  expect(calls).toContainEqual(["/v1/worlds/w_one/rooms", { lead: "A_one", agents: ["A_two"] }]);
  expect(calls).toContainEqual([
    "/v1/worlds/w_one/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV/turns",
    { to: "A_one", mode: "quick", text: "Why?" },
  ]);
  expect(calls).toContainEqual([
    "/v1/worlds/w_one/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV/changes",
    { proposal_id: "01ARZ3NDEKTSV4RRFFQ69G5FAW", text: "Revise with sources" },
  ]);
});
it("MR-12/HR-1 rejects foreign rooms and unreadable replies without fixture fallback", async () => {
  expect(() => roomOf(room, "other")).toThrow();
  expect(() => roomOf({ ...room, credits_spent: "zero" }, "w_one")).toThrow();
  const client = {
    getJson: vi.fn().mockRejectedValue(new Error("Access denied")),
    postJson: vi.fn(),
  };
  await act(async () => {
    mount(<MeetingHall worldId="w_one" client={client} />);
  });
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("Access denied");
  expect(client.postJson).not.toHaveBeenCalled();
});

async function tap(text: string) {
  const button = [...document.querySelectorAll("button")].find((b) => b.textContent === text);
  if (!button) throw new Error(`Missing ${text}`);
  await act(async () => button.click());
}
async function clickLabel(text: string) {
  const label = [...document.querySelectorAll("label")].find((l) => l.textContent?.includes(text));
  const box = label?.querySelector("input");
  if (!box) throw new Error(`Missing ${text}`);
  await act(async () => box.click());
}
async function enter(text: string, value: string) {
  const label = [...document.querySelectorAll("label")].find((l) => l.textContent?.includes(text));
  const field = label?.querySelector("textarea");
  if (!field) throw new Error(`Missing ${text}`);
  await act(async () => {
    field.value = value;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
