// The Needs-you queue (PRD 10.2, 10.3, 18.3 S-06), derived from recorded events alone (HR-1, HR-5)
// by the reducer the gate sheet also uses (reduce.ts). A card opens with its event
// (approval.requested for a gate, question.routed for a question) and closes with the event that
// answers it, within its own run. Only a card of this run is joined to an item: same id and same
// run id. A card the client lists for another run is never shown, and an item without its card
// still shows what the event says.
import type { Card, Event, Layout } from "@tilo/contracts";
import { agentNames } from "../world/runSummary";
import { reduceNeedsYou } from "./reduce";

export type QueueKind = "gate" | "question";

export interface QueueItem {
  readonly kind: QueueKind;
  readonly cardId: string;
  readonly runId: string;
  /** The plan gate a gate item waits at; null for a question. */
  readonly gateId: string | null;
  /** approval.requested or question.routed: the event that opened it. */
  readonly opened: Event;
  /** The card of this run with this id, or null when the client has none (never another run's). */
  readonly card: Card | null;
}

/** The card of this run with this id: same id and same run id, never another run's. */
export const cardFor = (
  cards: readonly Card[],
  cardId: string | null,
  runId: string,
): Card | null =>
  runId ? (cards.find((c) => c.id === cardId && c.run_id === runId) ?? null) : null;

/** Items still waiting after `events`, oldest first. `cards` are the client's. A gate a decision or
 * a policy closed is gone, and so is a question its answer closed. */
export function deriveQueue(events: readonly Event[], cards: readonly Card[] = []): QueueItem[] {
  const { gates, questions } = reduceNeedsYou(events);
  const items: Array<Omit<QueueItem, "card">> = [
    ...gates.flatMap((g) =>
      g.outcome.state === "waiting" && g.requested && g.cardId
        ? [
            {
              kind: "gate" as const,
              cardId: g.cardId,
              runId: g.runId,
              gateId: g.gateId,
              opened: g.requested,
            },
          ]
        : [],
    ),
    ...questions.map((q) => ({
      kind: "question" as const,
      cardId: q.cardId,
      runId: q.opened.run_id,
      gateId: null,
      opened: q.opened,
    })),
  ];
  return items
    .sort((a, b) => a.opened.seq - b.opened.seq)
    .map((item) => ({ ...item, card: cardFor(cards, item.cardId, item.runId) }));
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
