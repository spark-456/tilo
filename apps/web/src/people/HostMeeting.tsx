// "Host this meeting" on S-26 (FR-MTG-09, ticket MEETINGS-1): the owner asks Tilo to host a scheduled
// bot meeting. The request makes a one-gate run; the reply is only its world id. The T3 gate card is
// then read from that world's cards and shown here, answered by the person. This client never approves
// (T3 always needs a person), and nothing is created in the calendar until they do. Neutral role
// tokens only; no design export covers it, and nothing here animates.
import type { Card, Meeting } from "@tilo/contracts";
import { useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { CardHead, CardOptions, useAnswer } from "../needs-you/CardView";
import { AppLink } from "../screens/AppLink";
import { NOT_CONNECTED, canAskToHost, canHostMeeting, hostFailureText } from "./host";

type View =
  | { readonly kind: "idle" }
  | { readonly kind: "sending" }
  | { readonly kind: "waiting" }
  | { readonly kind: "card"; readonly card: Card }
  | { readonly kind: "no_card" }
  | { readonly kind: "unreadable" }
  | { readonly kind: "error"; readonly message: string };

const SAYS: Readonly<Record<string, string>> = {
  sending: "Asking Tilo to prepare the invitation…",
  waiting: "Waiting for the approval card…",
  card: "Waiting for your decision. Nothing is created in the calendar until you approve.",
  no_card:
    "Hosting was requested, but the approval card has not appeared yet. Look in Needs you; it will be there when it is ready.",
  unreadable:
    "Hosting was requested, but Tilo could not load its approval card. Look in Needs you.",
};

/** The gate this feature opens: the one T3 card for creating the event (FR-MTG-09). */
const isHostGate = (c: Card): boolean =>
  c.kind === "gate" && c.gate?.action.type === "create_meeting_event" && c.gate.risk_tier === "T3";

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function HostGate({ card, client }: { card: Card; client: TiloClient }) {
  const answer = useAnswer(client, card.id);
  const gate = card.gate;
  return (
    <article className="need-card" data-testid="need-card" data-rung={card.rung}>
      <CardHead card={card} layout={null} />
      {gate && (
        <dl className="gate-facts" data-testid="gate-facts">
          <div>
            <dt>The exact action</dt>
            <dd>{gate.action.exact}</dd>
          </div>
          <div>
            <dt>Who receives it</dt>
            <dd>{gate.recipients.length > 0 ? gate.recipients.join(", ") : "No one else."}</dd>
          </div>
          <div>
            <dt>Can it be undone?</dt>
            <dd>
              {gate.irreversible
                ? "Once sent, it can't be unsent."
                : "Yes, you can undo it afterwards."}
            </dd>
          </div>
          <div>
            <dt>Risk tier</dt>
            <dd>T3: a person always decides this.</dd>
          </div>
        </dl>
      )}
      <CardOptions card={card} answer={answer} preselect={false} />
    </article>
  );
}

export function HostMeeting({
  meeting,
  me,
  pollMs = 1000,
  tries = 10,
}: { meeting: Meeting; me: string; pollMs?: number; tries?: number }) {
  const client = useClient();
  const [view, setView] = useState<View>({ kind: "idle" });
  const busy = useRef(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  if (!canHostMeeting(meeting, me)) return null;

  const show = (v: View) => {
    if (live.current) setView(v);
  };
  const host = async () => {
    if (busy.current) return;
    busy.current = true;
    if (!canAskToHost(client)) {
      busy.current = false;
      return show({ kind: "error", message: NOT_CONNECTED });
    }
    show({ kind: "sending" });
    let worldId: string;
    try {
      worldId = (await client.hostMeeting(meeting.id)).world_id;
    } catch (error) {
      busy.current = false;
      return show({ kind: "error", message: hostFailureText(error) });
    }
    // The run has started: asking again would only be refused, so the button stays gone from here on.
    show({ kind: "waiting" });
    try {
      for (let i = 0; i < tries && live.current; i++) {
        const card = (await client.listCards(worldId)).find(isHostGate);
        if (card) return show({ kind: "card", card });
        await wait(pollMs);
      }
      show({ kind: "no_card" });
    } catch {
      show({ kind: "unreadable" });
    }
  };

  const started = view.kind !== "idle" && view.kind !== "sending" && view.kind !== "error";
  return (
    <div data-testid="host-meeting">
      <div className="minutes-bar">
        {!started && (
          <button
            type="button"
            className="primary"
            disabled={view.kind === "sending"}
            aria-busy={view.kind === "sending" ? "true" : undefined}
            onClick={host}
          >
            Host this meeting
          </button>
        )}
        <p>
          Tilo creates the calendar event and invites the people on the list. Nothing is sent until
          you approve.
        </p>
      </div>
      <output className="section-note host-status" data-testid="host-status">
        {view.kind === "error" ? view.message : (SAYS[view.kind] ?? "")}
      </output>
      {(view.kind === "no_card" || view.kind === "unreadable") && (
        <AppLink to="/needs-you" className="pill">
          Open Needs you
        </AppLink>
      )}
      {view.kind === "card" && <HostGate card={view.card} client={client} />}
    </div>
  );
}
