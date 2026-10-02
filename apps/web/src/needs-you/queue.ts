// The Needs-you queue of one run (PRD 10.2, 10.3, 18.3 S-06), derived from its recorded events
// alone (HR-1, HR-5). A card opens with its event (approval.requested for a gate, question.routed
// for a question) and closes with the event that answers it (approval.resolved, question.answered).
// Only a card of this run is joined to an item: same id and same run id. A card the client lists
// for another run is never shown, and an item without its card still shows what the event says.
import type { Card, Event, Layout } from "@tilo/contracts";
import { agentNames } from "../world/runSummary";

export type QueueKind = "gate" | "question";

export interface QueueItem {
  readonly kind: QueueKind;
  readonly cardId: string;
  /** The plan gate a gate item waits at; null for a question. */
  readonly gateId: string | null;
  /** approval.requested or question.routed: the event that opened it. */
  readonly opened: Event;
  /** The card of this run with this id, or null when the client has none (never another run's). */
  readonly card: Card | null;
}

const text = (e: Event, key: string): string | null => {
  const v = (e.data as Record<string, unknown>)[key];
  return typeof v === "string" ? v : null;
};

/** The card of this run with this id: same id and same run id, never another run's. */
export const cardFor = (
  cards: readonly Card[],
  cardId: string | null,
  runId: string,
): Card | null => cards.find((c) => c.id === cardId && c.run_id === runId) ?? null;

/** Items still waiting after `events` (in seq order), oldest first. `cards` are the client's. */
export function deriveQueue(events: readonly Event[], cards: readonly Card[] = []): QueueItem[] {
  const open = new Map<string, Omit<QueueItem, "card">>();
  for (const e of events) {
    const cardId = text(e, "card_id");
    if (e.type === "approval.requested" && cardId) {
      open.set(cardId, { kind: "gate", cardId, gateId: text(e, "gate_id"), opened: e });
    } else if (e.type === "question.routed" && cardId) {
      open.set(cardId, { kind: "question", cardId, gateId: null, opened: e });
    } else if (e.type === "approval.resolved") {
      const gateId = text(e, "gate_id");
      for (const [id, item] of open) {
        if (id === cardId || (gateId !== null && item.gateId === gateId)) open.delete(id);
      }
    } else if (e.type === "question.answered") {
      // The answer names its question by `cause`, else by the agent that asked (its `target`);
      // an answer that names neither closes nothing, since a guess could close the wrong card.
      const asked = [...open.values()].filter((i) => i.kind === "question");
      const match =
        asked.find((i) => e.cause !== null && i.opened.id === e.cause) ??
        asked.find((i) => i.opened.actor === e.target);
      if (match) open.delete(match.cardId);
    }
  }
  return [...open.values()].map((item) => ({
    ...item,
    card: cardFor(cards, item.cardId, item.opened.run_id),
  }));
}

/** "Research lead", the agent that asked: names, never ids (a person reads these). */
export function askedBy(layout: Layout | null, e: Event): string {
  const agent = layout ? agentNames(layout).get(e.actor) : undefined;
  const district = layout?.semantic.levels
    .flatMap((l) => l.districts)
    .find((d) => d.id === e.district)?.name;
  return [agent ?? "An agent", district].filter(Boolean).join(" · ");
}

/** The words on the rung label; colour never carries the rung alone (PRD 18.2). */
export const RUNG: Readonly<Record<Card["rung"], { label: string; tone: string }>> = {
  needs_you: { label: "Needs you", tone: "needs" },
  blocked: { label: "Blocked", tone: "blocked" },
  meeting: { label: "Meeting invite", tone: "needs" },
  gate: { label: "Approval gate", tone: "gate" },
  consent: { label: "Connection consent", tone: "needs" },
};

/** The rung of an item: its card's, else what the opening event implies. */
export const rungOf = (item: QueueItem): { label: string; tone: string } =>
  RUNG[item.card?.rung ?? (item.kind === "gate" ? "gate" : "needs_you")];
