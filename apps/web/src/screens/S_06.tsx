// S-06 Needs-you queue and card (PRD 18.3, 10.2, 10.3). One row per card that waits for a person,
// after the "Needs you" block of design/source "Tilo 2 Balanced Refined.dc.html" 2-1: a rung label
// with a word (never colour alone), what happened, who asked and when. The queue follows this run's
// recorded events (HR-1): a card opens with its event and closes with the one that answers it
// (needs-you/queue.ts, within its own run). A card the client lists for another run never appears.
// A question opens as a card below the queue; a gate is answered on its own sheet (S-07).
import type { Layout } from "@tilo/contracts";
import { useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { CardView, useAnswer } from "../needs-you/CardView";
import { type QueueItem, askedBy, deriveQueue, rungOf } from "../needs-you/queue";
import { elapsed } from "../world/runLog";
import { alsoWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Chip, EmptyState, Page, Row, Section, Soon, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

/** The card of one waiting question, answerable; or what the event says when the client has no
 * question card for it (a gate's card is never answered from the queue: it has its own sheet). */
function QuestionCard({ item, layout }: { item: QueueItem; layout: Layout | null }) {
  const answer = useAnswer(useClient(), item.cardId);
  if (item.card?.kind !== "needs_you") {
    return (
      <>
        <p className="need-what">{item.opened.summary}</p>
        <p className="section-note">
          This replay did not record the card for this question, so it cannot be answered here.
        </p>
        <Soon labels={["Answer"]} />
      </>
    );
  }
  return <CardView card={item.card} layout={layout} answer={answer} />;
}

export function S_06() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layoutRemote] = useRemote("load the world", () => client.getLayout(worldId));
  const [cards, retry] = useRemote("load the cards", () => client.listCards(worldId));
  const [openId, setOpenId] = useState<string | null>(null);
  const layout = layoutRemote.status === "ready" ? layoutRemote.value : null;
  const items = deriveQueue(events, cards.status === "ready" ? cards.value : []);
  const open = items.find((i) => i.kind === "question" && i.cardId === openId);
  // A row that closes while it has focus would drop focus to the page body: it goes to the queue
  // heading instead, so keyboard and screen-reader users keep their place.
  const heading = useRef<HTMLHeadingElement>(null);
  const count = useRef(items.length);
  const inQueue = useRef(false); // the last focus was on a row's control
  useEffect(() => {
    const track = (e: FocusEvent) => {
      inQueue.current =
        e.target instanceof Element && !!e.target.closest('[data-testid="needs-queue"]');
    };
    document.addEventListener("focusin", track);
    return () => document.removeEventListener("focusin", track);
  }, []);
  useEffect(() => {
    const closed = items.length < count.current;
    count.current = items.length;
    const lost = !document.activeElement || document.activeElement === document.body;
    if (closed && inQueue.current && lost) heading.current?.focus();
  }, [items.length]);
  return (
    <Page
      testid="needs-you"
      title="Needs you"
      sub="Questions and approvals that wait for a person. Other work keeps going while you decide."
    >
      <Section title="Waiting for you" reserve={[8, 12]} headingRef={heading}>
        <Loaded what="the cards" remote={cards} retry={retry} isEmpty={() => false}>
          {() =>
            items.length === 0 ? (
              <EmptyState
                testid="needs-empty"
                title="Nothing needs you"
                line="Tilo asks here when it needs a decision."
                action={{ label: "See your worlds", to: "/worlds" }}
              />
            ) : (
              <ul className="blist" data-testid="needs-queue">
                {items.map((item) => {
                  const rung = rungOf(item);
                  const name = item.card?.what_happened ?? item.opened.summary;
                  const gate = (item.opened.data ?? {}) as {
                    action_type?: string;
                    irreversible?: boolean;
                  };
                  return (
                    <Row
                      key={`${item.runId}/${item.cardId}`}
                      name={name}
                      sub={[
                        askedBy(layout, item.opened),
                        `${elapsed(events, item.opened)} into the run`,
                        item.kind === "gate" && gate.action_type && words(gate.action_type),
                        item.kind === "gate" && gate.irreversible && "Cannot be undone",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      state={<Chip tone={rung.tone}>{rung.label}</Chip>}
                    >
                      {item.kind === "gate" ? (
                        <AppLink
                          to={alsoWorld(
                            `/needs-you/gate?run=${encodeURIComponent(item.runId)}&gate=${encodeURIComponent(item.gateId ?? "")}`,
                            worldId,
                          )}
                          className="pill"
                          aria-label={`Review the gate: ${name}`}
                        >
                          Review the gate
                        </AppLink>
                      ) : (
                        <button
                          type="button"
                          className="secondary"
                          aria-label={`Answer: ${name}`}
                          aria-pressed={item.cardId === openId}
                          onClick={() => setOpenId(item.cardId === openId ? null : item.cardId)}
                        >
                          Answer
                        </button>
                      )}
                    </Row>
                  );
                })}
              </ul>
            )
          }
        </Loaded>
      </Section>
      {open && (
        <Section title="The card">
          <QuestionCard key={`${open.runId}/${open.cardId}`} item={open} layout={layout} />
        </Section>
      )}
    </Page>
  );
}
