// Dev only (routes.tsx adds it under import.meta.env.DEV, like /screens): the six contract card
// fixtures drawn with the card and gate-sheet components, for layout and accessibility checks at
// both viewports, plus the two gate variants the village replay does not show and one answerable
// gate on a stub client, so the filled primary button can be reviewed. These cards belong to
// another run than the replay, so they are never offered as this run's queue; the stub client
// records nothing and no event ever closes the card, so it ends as "No confirmation recorded yet".
// FR-CHN-01: the same card shows the same fields on desktop and mobile.
import type { Card } from "@tilo/contracts";
import { useState } from "react";
import { FixtureClient } from "../api/fixtureClient";
import { CARDS_VALID } from "../api/fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { EVENT_POLICY_APPLIED } from "../api/fixtures/policy";
import { Page, Section } from "../screens/kit";
import { CardView, useAnswer } from "./CardView";
import { GateSheet } from "./GateSheet";
import { type GateRecord, gatesOf } from "./gates";

const waiting = (card: Card): GateRecord => ({
  gateId: card.gate?.id ?? "G1",
  runId: card.run_id,
  cardId: card.id,
  requested: null,
  outcome: { state: "waiting" },
});

/** One gate sheet whose Approve, Edit first and Hold go to a stub client (no events follow). */
function Answerable({ card }: { card: Card }) {
  const [client] = useState(() => new FixtureClient());
  const answer = useAnswer(client, card.id, 4000);
  return (
    <GateSheet record={waiting(card)} card={card} layout={LAYOUT_VILLAGE_BASIC} answer={answer} />
  );
}

export function CardsGallery() {
  const person = gatesOf(EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= 37));
  const policy = gatesOf([EVENT_POLICY_APPLIED]);
  const reversible = CARDS_VALID.find((c) => c.gate?.irreversible === false);
  return (
    <Page
      testid="cards-gallery"
      title="Card fixtures"
      sub="Dev only. Contract fixture cards of another run, drawn to check layout. Not this run's queue."
    >
      <Section title="Contract cards">
        <div className="gallery-grid">
          {CARDS_VALID.map((card, i) =>
            card.gate ? (
              <GateSheet
                // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of fixtures that share ids.
                key={i}
                record={waiting(card)}
                card={card}
                layout={LAYOUT_VILLAGE_BASIC}
                answer={null}
              />
            ) : (
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of fixtures that share ids.
              <CardView key={i} card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />
            ),
          )}
        </div>
      </Section>
      <Section title="Gates the replay does not show">
        <div className="gallery-grid">
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
      </Section>
      {reversible && (
        <Section title="Answerable gate (stub client)">
          <div className="gallery-grid">
            <Answerable card={reversible} />
          </div>
        </Section>
      )}
    </Page>
  );
}
