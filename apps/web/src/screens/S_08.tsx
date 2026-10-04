import { useClient } from "../api/ClientProvider";
import { useAnswer } from "../needs-you/CardView";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section, Soon, field, nameOf, useFixtureRun } from "./kit";

export function S_08() {
  const client = useClient();
  const { events } = useFixtureRun();

  const request = events.find(
    (e) =>
      e.type === "connection.requested" &&
      !events.some(
        (x) =>
          (x.type === "connection.consented" && field(x, "card_id") === field(e, "card_id")) ||
          (x.type === "connection.revoked" &&
            x.seq > e.seq &&
            field(x, "connector") === field(e, "connector")),
      ),
  );

  const cardId = request ? String(field(request, "card_id") || "") : "";
  const answer = useAnswer(client, cardId);

  if (!request) {
    return (
      <Page
        testid="consent-sheet-page"
        title="Connection consent"
        sub="Approve access to your accounts."
      >
        <Section title="No request waiting">
          <p className="empty-note" data-testid="consent-empty">
            No connection is asking for consent right now.
          </p>
        </Section>
      </Page>
    );
  }

  const connectorName = nameOf(String(field(request, "connector") || ""));
  const scopes = (field(request, "scopes") as string[]) || [];
  const writeActions = (field(request, "write_actions") as string[]) || [];

  return (
    <Page
      testid="consent-sheet-page"
      title={`Connect ${connectorName}`}
      sub="Review what Tilo can do before you approve."
    >
      <Section title="What Tilo will do" reserve={[8, 12]}>
        <div className="gate-facts">
          <div>
            <dt>Why</dt>
            <dd>{request.summary}</dd>
          </div>
          <div>
            <dt>Scopes</dt>
            <dd>{scopes.length > 0 ? scopes.join(", ") : "No specific scopes listed"}</dd>
          </div>
          {writeActions.length > 0 && (
            <div>
              <dt>Write actions</dt>
              <dd>{writeActions.join(", ")}</dd>
            </div>
          )}
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
        </div>
        <div className="need-bar">
          <div className="need-actions">
            <button
              type="button"
              className="primary"
              disabled={answer.pending !== null}
              aria-busy={answer.pending === "allow" ? "true" : undefined}
              onClick={() => answer.send("allow", "")}
            >
              Allow
            </button>
            <button
              type="button"
              className="secondary"
              disabled={answer.pending !== null}
              aria-busy={answer.pending === "not_now" ? "true" : undefined}
              onClick={() => answer.send("not_now", "")}
            >
              Not now
            </button>
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
        {answer.error && (
          <p className="need-error" role="alert">
            {answer.error}
          </p>
        )}
      </Section>
    </Page>
  );
}
