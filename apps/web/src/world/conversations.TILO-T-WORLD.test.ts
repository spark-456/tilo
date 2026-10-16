/**
 * TILO-T-WORLD step 2 (FR-WLD-04, HR-1, MR-12): the Conversations list is the recorded messages between agents and
 * people, read from the same events the Story reads. Only what an event recorded appears; the words of a room turn
 * live in the archive and arrive separately (`words`), never invented.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { type Message, conversationsOf, pairOf, withWords } from "./conversations";

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents() as unknown as Event[];

let n = 0;
function ev(type: string, actor: string, target: string, data: object = {}, summary = "x"): Event {
  n += 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(n).padStart(19, "0")}`,
    seq: n,
    ts: `2026-10-16T09:00:${String(n).padStart(2, "0")}.000Z`,
    world_id: "w",
    run_id: "r",
    type,
    actor,
    target,
    level: "L1",
    district: "D1",
    item: null,
    severity: "info",
    credits: 0,
    summary,
    cause: null,
    vis: "all",
    authz: null,
    data,
    trace: {},
  } as unknown as Event;
}

test("FR-WLD-04 TILO-T-WORLD conversations: every handoff of the recorded run is a message with the envelope's real note", () => {
  const messages = conversationsOf(layout, events);
  const handoffs = events.filter((e) => e.type === "agent.handoff");
  expect(handoffs.length).toBeGreaterThan(0);
  for (const h of handoffs) {
    const note = (h.data as { envelope?: { summary?: string } }).envelope?.summary;
    const m = messages.find((x) => x.seq === h.seq);
    expect(m?.kind).toBe("handoff");
    expect(m?.from).toBe(h.actor);
    expect(m?.to).toBe(h.target);
    expect(m?.text).toBe(note ?? h.summary);
  }
});

test("FR-WLD-04 TILO-T-WORLD conversations: messages come in seq order and only from conversation event types", () => {
  const messages = conversationsOf(layout, events);
  expect(messages.map((m) => m.seq)).toEqual([...messages.map((m) => m.seq)].sort((a, b) => a - b));
  const talk = new Set([
    "agent.assigned",
    "agent.handoff",
    "agent.help_requested",
    "question.routed",
    "question.answered",
    "artifact.reviewed",
    "meeting.convened",
    "meeting.asked",
    "meeting.replied",
    "meeting.change_requested",
    "meeting.adjourned",
  ]);
  for (const m of messages)
    expect(talk.has(events.find((e) => e.seq === m.seq)?.type ?? "")).toBe(true);
});

test("FR-WLD-04 TILO-T-WORLD conversations: a handoff carries its acceptance criteria and where it happened", () => {
  n = 0;
  const run = [
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev("agent.handoff", "A_s1", "A_l1", {
      envelope: {
        summary: "Triaged 12 emails.",
        acceptance_criteria: ["One category each", "Flag suspicious"],
      },
    }),
  ];
  const [m] = conversationsOf(layout, run);
  expect(m?.text).toBe("Triaged 12 emails.");
  expect(m?.detail).toEqual(["One category each", "Flag suspicious"]);
  expect(m?.where).toBeNull(); // A_s1 has no recorded place yet: nothing is guessed
  const placed = conversationsOf(layout, [
    ...run.slice(0, 2),
    ev("agent.moved", "A_s1", "B2", { from: "B1" }),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "ok" } }),
  ]);
  expect(placed[0]?.where).toBe("B2");
});

test("FR-WLD-04 TILO-T-WORLD conversations: a room turn has no text of its own until the archive's words arrive", () => {
  n = 0;
  const run = [
    ev("meeting.convened", "u_owner", "A_l1", { room_id: "R1", lead: "A_l1", agents: ["A_s1"] }),
    ev("meeting.asked", "u_owner", "A_s1", { room_id: "R1", turn: 1, to: "A_s1", mode: "quick" }),
    ev("meeting.replied", "A_s1", "u_owner", { room_id: "R1", turn: 1, outcome: "answered" }),
  ];
  const base = conversationsOf(layout, run);
  const asked = base.find((m) => m.kind === "asked") as Message;
  expect(asked.text).toBeNull();
  expect(asked.room).toBe("R1");
  expect(asked.turn).toBe(1);
  const filled = withWords(base, (room, turn, side) =>
    room === "R1" && turn === 1 ? `${side} words` : null,
  );
  expect(filled.find((m) => m.kind === "asked")?.text).toBe("asked words");
  expect(filled.find((m) => m.kind === "replied")?.text).toBe("replied words");
  expect(base.find((m) => m.kind === "asked")?.text).toBeNull(); // the input is not mutated
});

test("FR-WLD-04 TILO-T-WORLD conversations: pairOf is the same pair either way round", () => {
  expect(pairOf("A_l1", "A_s1")).toBe(pairOf("A_s1", "A_l1"));
});
