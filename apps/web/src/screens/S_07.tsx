// S-07 Gate sheet (PRD 18.3, 18.4): one gate of this run, person or policy. Which gate: the one
// `?run=&gate=` names (a gate id repeats across runs, so the run names it too), else the one that
// waits, else the latest. A gate that is asked for and not recorded says so; another gate never
// stands in for it. The sheet follows the gate's recorded events (needs-you/GateSheet.tsx, HR-1,
// HR-7) and draws from them even when the cards cannot load: only the answer controls degrade.
// Answering sends the person's choice through the client and then waits for the recorded event.
import type { Card, Layout } from "@tilo/contracts";
import { useEffect, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { useAnswer } from "../needs-you/CardView";
import { GateSheet } from "../needs-you/GateSheet";
import { type GateRecord, gatesOf } from "../needs-you/gates";
import { cardFor } from "../needs-you/queue";
import { gateKey } from "../needs-you/reduce";
import { Page, Section, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

/** Its own component, keyed by the request, so the answer state belongs to one request: after
 * Edit first and a redraft, the new request starts with nothing pending. */
function GatePanel({
  record,
  cards,
  layout,
}: { record: GateRecord; cards: readonly Card[]; layout: Layout | null }) {
  const card = cardFor(cards, record.cardId, record.runId);
  const answer = useAnswer(useClient(), card?.id ?? "");
  return <GateSheet record={record} card={card} layout={layout} answer={card ? answer : null} />;
}

/** The gate the address asks for: null when it names none, `false` when none (or, with no run
 * named, more than one) matches. */
function asked(records: readonly GateRecord[], run: string | null, gate: string | null) {
  if (gate === null) return null;
  const hits = records.filter((g) => g.gateId === gate && (run === null || g.runId === run));
  return (hits.length === 1 && hits[0]) || false;
}

export function S_07() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const [cards, retry] = useRemote("load the cards", () => client.listCards(worldId));
  const records = gatesOf(events);
  const [want] = useState(() => {
    const q = new URLSearchParams(window.location.search);
    return { run: q.get("run"), gate: q.get("gate") };
  });
  const [sticky, setSticky] = useState<string | null>(null);
  const named = asked(records, want.run, want.gate);
  const record =
    named === null
      ? (records.find((g) => gateKey(g.runId, g.gateId) === sticky) ??
        records.find((g) => g.outcome.state === "waiting") ??
        records[records.length - 1] ??
        null)
      : named || null;
  // Once a gate is shown it stays: a newer gate arriving never swaps the sheet under the person.
  useEffect(() => {
    if (named === null && sticky === null && record)
      setSticky(gateKey(record.runId, record.gateId));
  }, [named, sticky, record]);
  return (
    <Page
      testid="gate-sheet-page"
      title="Approval gate"
      sub="The exact action, who receives it and whether it can be undone."
    >
      <Section title="The gate">
        <div className="flow-slot">
          {cards.status === "loading" ? (
            <output className="flow-loading">Loading the gate…</output>
          ) : record ? (
            <>
              {cards.status === "error" && (
                <div className="flow-notice" role="alert">
                  <p>
                    {cards.message} The gate below follows the recorded events; it cannot be
                    answered here.
                  </p>
                  <button type="button" className="secondary" onClick={retry}>
                    Try again
                  </button>
                </div>
              )}
              <GatePanel
                key={`${gateKey(record.runId, record.gateId)}/${record.requested?.id ?? ""}`}
                record={record}
                cards={cards.status === "ready" ? cards.value : []}
                layout={layout.status === "ready" ? layout.value : null}
              />
            </>
          ) : named === false ? (
            <p className="empty-note" data-testid="gate-not-found">
              That gate has not been recorded in this run.
            </p>
          ) : (
            <p className="empty-note" data-testid="gate-empty">
              No gate has come up in this run yet. Tilo asks here before anything leaves your hands.
            </p>
          )}
        </div>
      </Section>
    </Page>
  );
}
