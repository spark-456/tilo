// The Needs-you page (PRD 18.3 S-06, S-07, S-08; 10.2, 10.3): the queue of cards that wait for a person, one gate
// sheet and one connection-consent sheet, as pages of the Park shell. The queue follows this run's recorded events
// (HR-1): a card opens with its event and closes with the one that answers it (needs-you/queue.ts, within its own
// run). A card the client lists for another run never appears. A question opens as a card below the queue; a gate is
// answered on its own sheet. Every answer goes through the client and then waits for the recorded event.
import type { Card, ConnectionRequestedData, Event, Layout } from "@tilo/contracts";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { useClient, useWorldKnown } from "../api/ClientProvider";
import { isFieldsApi } from "../api/fields";
import { isItemApi } from "../api/item";
import { CardView, useAnswer } from "../needs-you/CardView";
import { GateSheet } from "../needs-you/GateSheet";
import { type GateRecord, gatesOf } from "../needs-you/gates";
import { type QueueItem, askedBy, cardFor, deriveQueue, rungOf } from "../needs-you/queue";
import { gateKey } from "../needs-you/reduce";
import { type Remote, useRemote } from "../screens/remote";
import { elapsed, useRunLog } from "../world/runLog";
import { alsoWorld, useRunWorld, withWorld } from "../world/worldContext";
import { NotFoundView } from "./NotFoundView";
import { ViewLink } from "./ViewLink";
import { nameOf, words } from "./text";

function Frame({
  title,
  lede,
  testid,
  children,
}: { title: string; lede: string; testid: string; children: ReactNode }) {
  return (
    <div className="park-view-root park-needs-root" data-testid={testid}>
      <section className="park-sheet park-view-sheet">
        <header className="park-view-head park-needs-head">
          <h1 className="park-view-title" tabIndex={-1}>
            {title}
          </h1>
          <p className="park-view-lede">{lede}</p>
        </header>
        {children}
      </section>
    </div>
  );
}

function Section({
  title,
  headingRef,
  children,
}: {
  title: string;
  headingRef?: RefObject<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section className="park-view-card park-needs-section">
      <h2 className="park-view-h2" tabIndex={-1} ref={headingRef}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Empty({
  testid,
  title,
  line,
  to,
  label,
}: { testid: string; title: string; line: string; to: string; label: string }) {
  return (
    <div className="park-view-empty" data-testid={testid}>
      <h3 className="park-view-h2 park-view-empty-title">{title}</h3>
      <p className="park-view-note">{line}</p>
      <ViewLink className="park-view-chiplink" to={to}>
        {label}
      </ViewLink>
    </div>
  );
}

/** A remote value's loading and error states; `children` renders the ready one. */
function Loaded<T>({
  what,
  remote,
  retry,
  children,
}: { what: string; remote: Remote<T>; retry: () => void; children: (v: T) => ReactNode }) {
  if (remote.status === "loading") {
    return <output className="park-view-note">Loading {what}…</output>;
  }
  if (remote.status === "error") {
    return (
      <div className="park-view-alert" role="alert">
        <p>{remote.message}</p>
        <button type="button" className="park-view-chiplink" onClick={retry}>
          Try again
        </button>
      </div>
    );
  }
  return <>{children(remote.value)}</>;
}

/** The card of one waiting question, answerable; or what the event says when the client has no question card for
 * it (a gate's card is never answered from the queue: it has its own sheet). */
function QuestionCard({ item, layout }: { item: QueueItem; layout: Layout | null }) {
  const client = useClient();
  const answer = useAnswer(client, item.cardId);
  const fields = isFieldsApi(client) ? client : null;
  if (item.card?.kind !== "needs_you") {
    return (
      <>
        <p className="need-what">{item.opened.summary}</p>
        <p className="park-view-note">
          This replay did not record the card for this question, so it cannot be answered here.
        </p>
      </>
    );
  }
  return <CardView card={item.card} layout={layout} answer={answer} fields={fields} />;
}

function Queue({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [layoutRemote] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const [cards, retry] = useRemote("load the cards", () => client.listCards(worldId));
  const [openId, setOpenId] = useState<string | null>(null);
  const layout = layoutRemote.status === "ready" ? layoutRemote.value : null;
  const items = deriveQueue(events, cards.status === "ready" ? cards.value : []);
  const open = items.find((i) => i.kind === "question" && i.cardId === openId);
  // A row that closes while it has focus would drop focus to the page body: it goes to the queue heading instead,
  // so keyboard and screen-reader users keep their place.
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
    <>
      <Section title="Waiting for you" headingRef={heading}>
        <Loaded what="the cards" remote={cards} retry={retry}>
          {() =>
            items.length === 0 ? (
              <Empty
                testid="needs-empty"
                title="Nothing needs you"
                line="Tilo asks here when it needs a decision."
                to={withWorld("/worlds", worldId)}
                label="See your worlds"
              />
            ) : (
              <ul className="park-view-rows park-needs-queue" data-testid="needs-queue">
                {items.map((item) => {
                  const rung = rungOf(item);
                  const name = item.card?.what_happened ?? item.opened.summary;
                  const gate = (item.opened.data ?? {}) as {
                    action_type?: string;
                    irreversible?: boolean;
                  };
                  const sub = [
                    askedBy(layout, item.opened),
                    `${elapsed(events, item.opened)} into the run`,
                    item.kind === "gate" && gate.action_type && words(gate.action_type),
                    item.kind === "gate" && gate.irreversible && "Cannot be undone",
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <li key={`${item.runId}/${item.cardId}`} className="park-needs-item">
                      <div className="park-needs-itemtext">
                        <span className="park-view-rowname">{name}</span>
                        <small>{sub}</small>
                      </div>
                      <span className="park-view-flag park-view-flag--needs">{rung.label}</span>
                      {item.kind === "gate" ? (
                        <ViewLink
                          to={alsoWorld(
                            `/needs-you/gate?run=${encodeURIComponent(item.runId)}&gate=${encodeURIComponent(item.gateId ?? "")}`,
                            worldId,
                          )}
                          className="park-view-chiplink"
                          aria-label={`Review the gate: ${name}`}
                        >
                          Review the gate
                        </ViewLink>
                      ) : (
                        <button
                          type="button"
                          className="park-view-chiplink"
                          aria-label={`Answer: ${name}`}
                          aria-pressed={item.cardId === openId}
                          onClick={() => setOpenId(item.cardId === openId ? null : item.cardId)}
                        >
                          Answer
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )
          }
        </Loaded>
      </Section>
      {open ? (
        <Section title="The card">
          <QuestionCard key={`${open.runId}/${open.cardId}`} item={open} layout={layout} />
        </Section>
      ) : null}
    </>
  );
}

/** Its own component, keyed by the request, so the answer state belongs to one request: after Edit first and a
 * redraft, the new request starts with nothing pending. */
function GatePanel({
  record,
  cards,
  layout,
}: { record: GateRecord; cards: readonly Card[]; layout: Layout | null }) {
  const card = cardFor(cards, record.cardId, record.runId);
  const client = useClient();
  const answer = useAnswer(client, card?.id ?? "");
  const item = isItemApi(client) ? client : null; // the live client only: a fixture run pins nothing to show
  return (
    <GateSheet
      record={record}
      card={card}
      layout={layout}
      answer={card ? answer : null}
      item={item}
    />
  );
}

/** The gate the address asks for: null when it names none, `false` when none (or, with no run named, more than
 * one) matches. */
function asked(records: readonly GateRecord[], run: string | null, gate: string | null) {
  if (gate === null) return null;
  const hits = records.filter((g) => g.gateId === gate && (run === null || g.runId === run));
  return (hits.length === 1 && hits[0]) || false;
}

/** One gate of this run, person or policy. Which gate: the one `?run=&gate=` names (a gate id repeats across runs,
 * so the run names it too), else the one that waits, else the latest. A gate that is asked for and not recorded says
 * so; another gate never stands in for it. The sheet draws from the recorded events even when the cards cannot
 * load: only the answer controls degrade. */
function Gate({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
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
    <Section title="The gate">
      {cards.status === "loading" ? (
        <output className="park-view-note">Loading the gate…</output>
      ) : record ? (
        <>
          {cards.status === "error" ? (
            <div className="park-view-alert" role="alert">
              <p>
                {cards.message} The gate below follows the recorded events; it cannot be answered
                here.
              </p>
              <button type="button" className="park-view-chiplink" onClick={retry}>
                Try again
              </button>
            </div>
          ) : null}
          <GatePanel
            key={`${gateKey(record.runId, record.gateId)}/${record.requested?.id ?? ""}`}
            record={record}
            cards={cards.status === "ready" ? cards.value : []}
            layout={layout.status === "ready" ? layout.value : null}
          />
        </>
      ) : named === false ? (
        <Empty
          testid="gate-not-found"
          title="Gate not found"
          line="That gate has not been recorded in this run."
          to={withWorld("/needs-you", worldId)}
          label="Back to the queue"
        />
      ) : (
        <Empty
          testid="gate-empty"
          title="No gate yet"
          line="No gate has come up in this run yet. Tilo asks here before anything leaves your hands."
          to={withWorld("/needs-you", worldId)}
          label="Back to the queue"
        />
      )}
    </Section>
  );
}

/** SEC-15 / SIGNIN (BQ-SIGNIN-1): the consent screen is In production without Google's review of the restricted
 * Gmail scopes, so Google shows an unverified-app warning before the Gmail grant. Said here first, in these words.
 * Not shown for a connector Google does not flag. */
const UNVERIFIED_NOTE =
  "Google will show a warning that this app is not verified, because Google has not finished reviewing Tilo's access to Gmail. Tilo asks only for the access listed above. To continue, choose Advanced on Google's page, then continue to Tilo.";
const GOOGLE_FLAGS = new Set(["gmail"]);

const cardIdOf = (e: Event): string => (e.data as ConnectionRequestedData).card_id;
const connectorOf = (e: Event): string => (e.data as ConnectionRequestedData).connector;

function ConsentSheet({ request, card }: { request: Event; card: Card | null }) {
  const client = useClient();
  const answer = useAnswer(client, cardIdOf(request));
  const scopes = card?.consent?.scopes;
  return (
    <>
      <dl className="park-view-facts park-needs-facts">
        <div>
          <dt>Why</dt>
          <dd>{request.summary}</dd>
        </div>
        <div>
          <dt>Scopes</dt>
          <dd>{scopes ? scopes.join(", ") : "Scopes are not available."}</dd>
        </div>
        <div>
          <dt>What Tilo never does</dt>
          <dd>Tilo never sees your password. You sign in directly with the provider.</dd>
        </div>
        <div>
          <dt>How to disconnect</dt>
          <dd>
            You can disconnect at any time from the Connectors page, or revoke access from the
            provider's security settings.
          </dd>
        </div>
      </dl>
      {GOOGLE_FLAGS.has(connectorOf(request)) ? (
        <p className="park-view-note" data-testid="consent-unverified-note">
          {UNVERIFIED_NOTE}
        </p>
      ) : null}
      {card ? (
        <div className="need-bar">
          <div className="need-actions">
            {card.options.map((o) => (
              <button
                key={o.id}
                type="button"
                className={o.id === "connect" ? "primary" : "secondary"}
                disabled={answer.pending !== null}
                aria-busy={answer.pending === o.id ? "true" : undefined}
                onClick={() => answer.send(o.id, "")}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className="need-status" aria-live="polite">
            {answer.pending ? <span>Waiting for confirmation…</span> : null}
            {answer.unconfirmed ? (
              <span>
                No confirmation has been recorded for your answer yet. You can answer again.
              </span>
            ) : null}
          </div>
        </div>
      ) : (
        <p className="park-view-note" data-testid="consent-no-card">
          The consent card for this request has not arrived, so there is nothing to answer yet.
        </p>
      )}
      {answer.error ? (
        <p className="need-error" role="alert">
          {answer.error}
        </p>
      ) : null}
    </>
  );
}

function ConsentRequest({ request, worldId }: { request: Event; worldId: string }) {
  const client = useClient();
  const [cards, retry] = useRemote("load the consent card", () => client.listCards(worldId));
  const cardId = cardIdOf(request);
  return (
    <Section title={`Connect ${nameOf(connectorOf(request))}`}>
      <Loaded what="the consent card" remote={cards} retry={retry}>
        {(all) => (
          <ConsentSheet
            request={request}
            card={all.find((c) => c.id === cardId && c.kind === "consent") ?? null}
          />
        )}
      </Loaded>
    </Section>
  );
}

/** A request is a connection.requested event of this run with no connection.consented for its card yet; what is
 * asked (connector and scopes) and what can be answered come from the consent card the event names, never from the
 * event itself or from a default. Only `connect` grants the connection. */
function Consent({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  // Keyed by run: events of another run never open a request here.
  const runId = events[0]?.run_id ?? null;
  const runEvents = runId ? events.filter((e) => e.run_id === runId) : events;
  const request = runEvents.find(
    (e) =>
      e.type === "connection.requested" &&
      !runEvents.some(
        (x) =>
          (x.type === "connection.consented" && cardIdOf(x) === cardIdOf(e)) ||
          (x.type === "connection.revoked" && x.seq > e.seq && connectorOf(x) === connectorOf(e)),
      ),
  );
  return request ? (
    // Keyed by the card so a second request starts with a fresh answer state.
    <ConsentRequest key={cardIdOf(request)} request={request} worldId={worldId} />
  ) : (
    <Section title="No request waiting">
      <p className="park-view-note" data-testid="consent-empty">
        No connection is asking for consent right now.
      </p>
    </Section>
  );
}

const COPY = {
  queue: {
    title: "Needs you",
    lede: "Questions and approvals that wait for a person. Other work keeps going while you decide.",
    testid: "needs-you",
  },
  gate: {
    title: "Approval gate",
    lede: "The exact action, who receives it and whether it can be undone.",
    testid: "gate-sheet-page",
  },
  consent: {
    title: "Connection consent",
    lede: "Approve access to your accounts.",
    testid: "consent-sheet-page",
  },
} as const;

/** One sheet of a run the client knows: the page body without the "which world" guard. */
export function NeedsYouSheet({
  sheet,
  worldId,
}: { sheet: "queue" | "gate" | "consent"; worldId: string }) {
  return (
    <Frame {...COPY[sheet]}>
      {sheet === "queue" ? (
        <Queue worldId={worldId} />
      ) : sheet === "gate" ? (
        <Gate worldId={worldId} />
      ) : (
        <Consent worldId={worldId} />
      )}
    </Frame>
  );
}

export function NeedsYouView({ sheet }: { sheet: "queue" | "gate" | "consent" }) {
  // The world is the addressed one, else the one this session started last. With a live API and neither there is no
  // run: the page says "No run yet" instead of asking the API about the fixture world.
  const worldId = useRunWorld();
  const known = useWorldKnown(worldId);
  const copy = COPY[sheet];
  if (worldId === null) {
    return (
      <Frame {...copy} lede="Nothing has started yet, so there is nothing to show here.">
        <Section title="No run yet">
          <p className="park-view-note" data-testid="no-run">
            No run yet. Describe some work and its run shows up here.
          </p>
          <ViewLink className="park-view-chiplink" to="/">
            Back to Home
          </ViewLink>
        </Section>
      </Frame>
    );
  }
  if (!known) {
    return <NotFoundView />;
  }
  return <NeedsYouSheet sheet={sheet} worldId={worldId} />;
}
