import type { Card, Layout } from "@tilo/contracts";
// S-07 Gate sheet (PRD 18.3, 18.4): one gate of this run, person or policy. Which gate: the
// `?gate=` the queue linked to, else the one that waits, else the latest. The sheet follows the
// gate's recorded events (needs-you/GateSheet.tsx, HR-1, HR-7). Answering sends the person's choice
// through the client and then waits for the recorded approval.resolved.
import { useEffect, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { useAnswer } from "../needs-you/CardView";
import { GateSheet } from "../needs-you/GateSheet";
import { type GateRecord, gatesOf } from "../needs-you/gates";
import { cardFor } from "../needs-you/queue";
import { Loaded } from "./FlowShell";
import { Page, Section, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

/** Its own component so the answer state belongs to one gate and resets with it. */
function GatePanel({
  record,
  cards,
  layout,
}: { record: GateRecord; cards: readonly Card[]; layout: Layout | null }) {
  const card = cardFor(cards, record.cardId, record.runId);
  const answer = useAnswer(useClient(), card?.id ?? "");
  return <GateSheet record={record} card={card} layout={layout} answer={card ? answer : null} />;
}

export function S_07() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout] = useRemote("load the world", () => client.getLayout(worldId));
  const [cards, retry] = useRemote("load the cards", () => client.listCards(worldId));
  const gates = gatesOf(events);
  const [chosen, setChosen] = useState(() =>
    new URLSearchParams(window.location.search).get("gate"),
  );
  const record =
    gates.find((g) => g.gateId === chosen) ??
    gates.find((g) => g.outcome.state === "waiting") ??
    gates[gates.length - 1] ??
    null;
  // Once a gate is shown it stays: a newer gate arriving never swaps the sheet under the person.
  useEffect(() => {
    if (chosen === null && record) setChosen(record.gateId);
  }, [chosen, record]);
  return (
    <Page
      testid="gate-sheet-page"
      title="Approval gate"
      sub="The exact action, who receives it and whether it can be undone."
    >
      <Section title="The gate">
        <Loaded what="the gate" remote={cards} retry={retry} isEmpty={() => false}>
          {(list) =>
            record ? (
              <GatePanel
                key={record.gateId}
                record={record}
                cards={list}
                layout={layout.status === "ready" ? layout.value : null}
              />
            ) : (
              <p className="empty-note" data-testid="gate-empty">
                No gate has come up in this run yet. Tilo asks here before anything leaves your
                hands.
              </p>
            )
          }
        </Loaded>
      </Section>
    </Page>
  );
}
