// S-06 Needs-you queue (PRD 18.3, 10.2, 10.3). One row per card that waits for a person, after the
// "Needs you" block of design/source "Tilo 2 Balanced Refined.dc.html" 2-1: a rung label with a
// word (never colour alone), what happened, who asked and when. The queue follows this run's
// recorded events (HR-1): a card opens with its event and closes with the one that answers it
// (needs-you/queue.ts). A card the client lists for another run never appears.
import { useEffect, useRef } from "react";
import { useClient } from "../api/ClientProvider";
import { askedBy, deriveQueue, rungOf } from "../needs-you/queue";
import { elapsed } from "../world/runLog";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Chip, Page, Row, Section, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

export function S_06() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout] = useRemote("load the world", () => client.getLayout(worldId));
  const [cards, retry] = useRemote("load the cards", () => client.listCards(worldId));
  const items = deriveQueue(events, cards.status === "ready" ? cards.value : []);
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
              <p className="empty-note" data-testid="needs-empty">
                Nothing needs you. Tilo asks here when it needs a decision.
              </p>
            ) : (
              <ul className="blist" data-testid="needs-queue">
                {items.map((item) => {
                  const rung = rungOf(item);
                  const action = (item.opened.data ?? {}) as {
                    action_type?: string;
                    irreversible?: boolean;
                  };
                  return (
                    <Row
                      key={`${item.runId}/${item.cardId}`}
                      name={item.card?.what_happened ?? item.opened.summary}
                      sub={[
                        askedBy(layout.status === "ready" ? layout.value : null, item.opened),
                        `${elapsed(events, item.opened)} into the run`,
                        item.kind === "gate" && action.action_type && words(action.action_type),
                        item.kind === "gate" && action.irreversible && "Cannot be undone",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      state={<Chip tone={rung.tone}>{rung.label}</Chip>}
                    >
                      {item.kind === "gate" && (
                        <AppLink
                          to={`/needs-you/gate?run=${encodeURIComponent(item.runId)}&gate=${encodeURIComponent(item.gateId ?? "")}`}
                          className="pill"
                          aria-label={`Review the gate: ${item.card?.what_happened ?? item.opened.summary}`}
                        >
                          Review the gate
                        </AppLink>
                      )}
                    </Row>
                  );
                })}
              </ul>
            )
          }
        </Loaded>
      </Section>
    </Page>
  );
}
