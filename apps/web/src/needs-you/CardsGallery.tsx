// Dev only (routes.tsx adds it under import.meta.env.DEV, like /screens): the six contract card
// fixtures drawn with the card and gate-sheet components, for layout and accessibility checks at
// both viewports, plus the two gate variants the village replay does not show. These cards belong
// to another run than the replay, so they are never offered as this run's queue; nothing here can
// be answered. FR-CHN-01: the same card shows the same fields on desktop and mobile.
import type { Event } from "@tilo/contracts";
import { CARDS_VALID } from "../api/fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { Page } from "../screens/kit";
import { CardView } from "./CardView";
import { GateSheet } from "./GateSheet";
import { gatesOf } from "./gates";

const first = EVENTS_VILLAGE_BASIC[0] as Event;
/** Shaped like contracts/fixtures/events/valid/policy.applied.json. */
const POLICY_APPLIED: Event = {
  ...first,
  seq: 133,
  type: "policy.applied",
  actor: "pol_autopilot_l2",
  target: "G1",
  summary: "Your Autopilot policy opened the gate; the reply sends in 60 s unless you cancel.",
  authz: { by: "policy", ref: "pol_autopilot_l2", at: "2026-09-29T09:42:16.000Z" },
  data: {
    policy_id: "pol_autopilot_l2",
    gate_id: "G1",
    outbox_id: "01JB5VQ0000000000000009006",
    action_type: "send_email",
    connector: "gmail",
    destination: "thread-supplier-1",
    district: "D1",
    risk_tier: "T2",
    level: "L2",
    instruction_id: "01JB5VQ0000000000000000131",
    undo_window_s: 60,
    item: { artifact_id: "art_followup_reply", version: 1 },
    credits: 2,
  },
};

export function CardsGallery() {
  const person = gatesOf(EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= 37));
  const policy = gatesOf([POLICY_APPLIED]);
  return (
    <Page
      testid="cards-gallery"
      title="Card fixtures"
      sub="Dev only. Contract fixture cards of another run, drawn to check layout. Not this run's queue."
    >
      <div className="gallery-grid">
        {CARDS_VALID.map((card, i) =>
          card.gate ? (
            <GateSheet
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of fixtures that share ids.
              key={i}
              record={{
                gateId: card.gate.id,
                cardId: card.id,
                runId: card.run_id,
                requested: null,
                outcome: { state: "waiting" },
              }}
              card={card}
              layout={LAYOUT_VILLAGE_BASIC}
              answer={null}
            />
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of fixtures that share ids.
            <CardView key={i} card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />
          ),
        )}
        {[...person, ...policy].map((record) => (
          <GateSheet
            key={record.outcome.state}
            record={record}
            card={null}
            layout={LAYOUT_VILLAGE_BASIC}
            answer={null}
          />
        ))}
      </div>
    </Page>
  );
}
