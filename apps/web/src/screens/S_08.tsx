// S-08 Connection consent sheet (FR-CON-03, PRD 18.4 "Access"). A request is a connection.requested
// event of this run with no connection.consented for its card yet; what is asked (connector and
// scopes) and what can be answered (the options) come from the consent card the event names, never
// from the event itself or from a default. Contract: card.schema.json consent branch and CR-13 fix
// the options to `connect` ("Connect") and `hold` ("Hold"); only `connect` grants the connection.
import type { Card, ConnectionRequestedData, Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { useAnswer } from "../needs-you/CardView";
import { Loaded } from "./FlowShell";
import { Page, Section, nameOf, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

/** SEC-15 / SIGNIN (BQ-SIGNIN-1): the consent screen is In production without Google's review of the restricted Gmail
 * scopes, so Google shows an unverified-app warning before the Gmail grant. Said here first, in these words (also in
 * services/api/tests/API_SIGNIN.md). Not shown for a connector Google does not flag. */
const UNVERIFIED_NOTE =
  "Google will show a warning that this app is not verified, because Google has not finished reviewing Tilo's access to Gmail. Tilo asks only for the access listed above. To continue, choose Advanced on Google's page, then continue to Tilo.";
const GOOGLE_FLAGS = new Set(["gmail"]);

const cardIdOf = (e: Event): string => (e.data as ConnectionRequestedData).card_id;
const connectorOf = (e: Event): string => (e.data as ConnectionRequestedData).connector;

export function S_08() {
  const { events } = useFixtureRun();
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

  return (
    <Page
      testid="consent-sheet-page"
      title="Connection consent"
      sub="Approve access to your accounts."
    >
      {request ? (
        // Keyed by the card so a second request starts with a fresh answer state.
        <Request key={cardIdOf(request)} request={request} />
      ) : (
        <Section title="No request waiting" reserve={[8, 12]}>
          <p className="empty-note" data-testid="consent-empty">
            No connection is asking for consent right now.
          </p>
        </Section>
      )}
    </Page>
  );
}

function Request({ request }: { request: Event }) {
  const client = useClient();
  const { worldId } = useFixtureRun();
  const cardId = cardIdOf(request);
  const [cards, retry] = useRemote("load the consent card", () => client.listCards(worldId));
  return (
    <Section title={`Connect ${nameOf(connectorOf(request))}`} reserve={[8, 12]}>
      <Loaded what="the consent card" remote={cards} retry={retry} isEmpty={() => false}>
        {(all) => (
          <Sheet
            request={request}
            card={all.find((c) => c.id === cardId && c.kind === "consent") ?? null}
          />
        )}
      </Loaded>
    </Section>
  );
}

function Sheet({ request, card }: { request: Event; card: Card | null }) {
  const client = useClient();
  const answer = useAnswer(client, cardIdOf(request));
  const scopes = card?.consent?.scopes;
  return (
    <>
      <dl className="gate-facts">
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
            You can disconnect at any time from the Connections page, or revoke access from the
            provider's security settings.
          </dd>
        </div>
      </dl>
      {GOOGLE_FLAGS.has(connectorOf(request)) && (
        <p className="empty-note" data-testid="consent-unverified-note">
          {UNVERIFIED_NOTE}
        </p>
      )}
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
            {answer.pending && <span>Waiting for confirmation…</span>}
            {answer.unconfirmed && (
              <span>
                No confirmation has been recorded for your answer yet. You can answer again.
              </span>
            )}
          </div>
        </div>
      ) : (
        <p className="empty-note" data-testid="consent-no-card">
          The consent card for this request has not arrived, so there is nothing to answer yet.
        </p>
      )}
      {answer.error && (
        <p className="need-error" role="alert">
          {answer.error}
        </p>
      )}
    </>
  );
}
