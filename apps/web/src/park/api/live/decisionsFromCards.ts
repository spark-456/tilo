// WIRE-3: tilo-api `GET /cards` items (S-06) as Park decisions. Only the served fields carry values; icon, done,
// toast and approvedTitle are empty and facts is absent, never a sample (HR-1..HR-7). Defaults: BQ-WIRE3-1..5.
// Pure: it never mutates its input and never imports fixtures.
import type { Card } from "@tilo/contracts";
import type { Decision, DecisionKey } from "../types";

export interface CardFeedItem {
  world_id: string;
  card_id: string;
  card: Card;
}

/**
 * The id of the option a tap answers with (BQ-WIRE3-2): a gate's `approve` and a consent card's `connect` (the
 * person's explicit act, never the suggested `hold`), otherwise the `suggested` one. Null when the card has none,
 * and a card with none is unreadable, so the Api never answers it.
 */
export function answerOption(card: Card): string | null {
  const want = card.kind === "gate" ? "approve" : card.kind === "consent" ? "connect" : null;
  const option = card.options.find((o) => (want === null ? o.suggested === true : o.id === want));
  return option?.id ?? null;
}

/** One opaque key per (world_id, card_id): the same pair always gives the same key (BQ-WIRE3-1). */
export const decisionKey = (worldId: string, cardId: string): DecisionKey =>
  `${encodeURIComponent(worldId)}:${encodeURIComponent(cardId)}` as unknown as DecisionKey;

/** The words a person reads beside a card whose tap does more than answer a question (BQ-WIRE3-4). */
function bodyOf(card: Card): string {
  if (needsFields(card))
    return `${card.why_it_matters}
Add it on the Needs you screen.`;
  const extra =
    card.kind === "gate" && card.gate
      ? [card.gate.action.exact, ...card.gate.recipients]
      : card.kind === "consent" && card.consent
        ? card.consent.scopes
        : [];
  return [card.why_it_matters, ...extra].join("\n");
}

/** A card that asks for fields (`provide`) is answered by typing them on the Needs you screen, never by a tap (L6c). */
const needsFields = (card: Card): boolean =>
  card.kind === "needs_you" && card.options.some((o) => o.id === "provide");

function decisionOf({ world_id, card_id, card }: CardFeedItem): Decision {
  const id = answerOption(card);
  return {
    k: decisionKey(world_id, card_id),
    world: world_id,
    title: card.what_happened,
    body: bodyOf(card),
    yes: needsFields(card) ? "" : (card.options.find((o) => o.id === id)?.label ?? ""), // "" = no tap
    icon: "",
    done: "",
    toast: "",
    approvedTitle: "",
  };
}

export function decisionsFromCards(items: readonly CardFeedItem[]): Decision[] {
  return items.map(decisionOf);
}
