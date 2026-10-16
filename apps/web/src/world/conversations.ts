// TILO-T-WORLD: the world's conversations, derived from the recorded events alone (HR-1), in the same order the Story
// reads them. A message is one event that is somebody saying something to somebody: a Lead giving a unit, a worker's
// handoff note, a question and its answer, a reviewer's verdict, a person's turn in a meeting room and the reply.
// The words of a room turn are only in the redacted archive (MR-12); `withWords` fills them in from there, and a turn
// with no words stays unworded: nothing is made up.
import type { Event, Layout } from "@tilo/contracts";
import { type WorldState, applyEvent, createInitialState, standingAt } from "./reducer";
import { isKnownType } from "./registry";

export type MessageKind =
  | "assigned"
  | "handoff"
  | "help"
  | "question"
  | "answer"
  | "review"
  | "convened"
  | "asked"
  | "replied"
  | "change"
  | "adjourned";

export interface Message {
  /** The event's seq: the message's key, and what a click on it flies the camera to. */
  readonly seq: number;
  readonly ts: string;
  readonly kind: MessageKind;
  /** Who said it and who it went to: agent ids from the layout, or a person's id. */
  readonly from: string;
  readonly to: string;
  /** What was said: the event's own words. Null for a room turn until its archive words arrive. */
  readonly text: string | null;
  /** A handoff's acceptance criteria, one line each. */
  readonly detail: readonly string[];
  /** The building, district or level the speaking agent stood at when it happened, from the record; or null. */
  readonly where: string | null;
  readonly room: string | null;
  readonly turn: number | null;
  readonly credits: number;
}

const KIND: Readonly<Record<string, MessageKind>> = {
  "agent.assigned": "assigned",
  "agent.handoff": "handoff",
  "agent.help_requested": "help",
  "question.routed": "question",
  "question.answered": "answer",
  "artifact.reviewed": "review",
  "meeting.convened": "convened",
  "meeting.asked": "asked",
  "meeting.replied": "replied",
  "meeting.change_requested": "change",
  "meeting.adjourned": "adjourned",
};

const record = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

/** The same key for a pair of speakers whichever way round: the filter by pair. */
export const pairOf = (a: string, b: string): string => (a < b ? `${a}|${b}` : `${b}|${a}`);

function wordsOf(event: Event, kind: MessageKind): { text: string | null; detail: string[] } {
  if (kind === "asked" || kind === "replied") return { text: null, detail: [] };
  if (kind === "handoff") {
    const envelope = record(record(event.data).envelope);
    const own = typeof envelope.summary === "string" ? envelope.summary.trim() : "";
    const criteria = Array.isArray(envelope.acceptance_criteria)
      ? envelope.acceptance_criteria.filter((c): c is string => typeof c === "string")
      : [];
    return { text: own || event.summary, detail: criteria };
  }
  return { text: event.summary, detail: [] };
}

function whereOf(state: WorldState, event: Event, kind: MessageKind): string | null {
  if (kind === "convened" || kind === "asked" || kind === "replied" || kind === "change")
    return state.hall;
  if (kind === "adjourned") return state.hall;
  const speaker = state.agents[event.actor] ?? state.agents[event.target];
  return speaker ? standingAt(state, speaker) : null;
}

export function messageOf(event: Event, state: WorldState): Message | null {
  const kind = isKnownType(event.type) ? KIND[event.type] : undefined;
  if (!kind) return null;
  const data = record(event.data);
  const { text, detail } = wordsOf(event, kind);
  const turn = typeof data.turn === "number" ? data.turn : null;
  return {
    seq: event.seq,
    ts: event.ts,
    kind,
    from: event.actor,
    to: event.target,
    text,
    detail,
    where: whereOf(state, event, kind),
    room: typeof data.room_id === "string" ? data.room_id : null,
    turn,
    credits: event.credits,
  };
}

/** Every message of the run so far, in seq order. `events` is the same slice the Story and the stage show. */
export function conversationsOf(layout: Layout, events: readonly Event[]): Message[] {
  let state = createInitialState(layout);
  const out: Message[] = [];
  for (const event of events) {
    const next = applyEvent(state, event, layout);
    if (next === state) continue; // a duplicate or out-of-order event is not a second message
    state = next;
    const message = messageOf(event, state);
    if (message) out.push(message);
  }
  return out;
}

/** The archive's words for the room turns that have them; the input is not changed. */
export function withWords(
  messages: readonly Message[],
  words: (room: string, turn: number, side: "asked" | "replied") => string | null | undefined,
): Message[] {
  return messages.map((m) => {
    if ((m.kind !== "asked" && m.kind !== "replied") || m.room === null || m.turn === null)
      return m;
    const text = words(m.room, m.turn, m.kind);
    return text ? { ...m, text } : m;
  });
}
