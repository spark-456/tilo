import type { Event } from "@tilo/contracts";
import type { ReactNode } from "react";
import { useClient, useIsFixtureClient } from "../../api/ClientProvider";
import { useAdminRead, useRunLog, useRunWorld, worldStatus } from "../../api/runAdmin";
import { Card } from "../components";

type Section = "mail" | "console" | "connections";
const authors: Record<string, string> = { policy: "Your rule", team_lead: "A Team Lead" };
const field = (event: Event, key: string): unknown => (event.data as Record<string, unknown>)[key];
const names: Record<string, string> = {
  gmail: "Gmail",
  google_drive: "Google Drive",
  email: "Email",
};
const nameOf = (id: string) =>
  names[id] ?? id.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <section aria-label={title}>
        <h2 className="park-team-h2">{title}</h2>
        {children}
      </section>
    </Card>
  );
}
const STARTING = {
  connected: "Connected",
  locked: "Not connected",
  requested: "Waiting for your consent",
  failed: "Access lost",
} as const;
/** The Connectors page's run-connection cards (Studio card look: Connectors.studio.css, `park-runconn-*`). */
function ConnBlock({
  title,
  line,
  children,
}: { title: string; line: string; children: ReactNode }) {
  return (
    <section className="park-runconn" aria-label={title}>
      <h2 className="park-runconn-title">{title}</h2>
      <p className="park-runconn-line">{line}</p>
      {children}
    </section>
  );
}
function Events({
  events,
  empty,
  testid,
}: { events: readonly Event[]; empty: string; testid?: string }) {
  return events.length ? (
    <ul data-testid={testid}>
      {events.map((event) => (
        <li key={event.seq}>
          {event.summary}
          {event.authz && (
            <p>
              Authorised by {authors[event.authz.by] ?? "You"} · {event.authz.at}
            </p>
          )}
        </li>
      ))}
    </ul>
  ) : (
    <p>{empty}</p>
  );
}
function RunSection({ section }: { section: Section }) {
  const worldId = useRunWorld();
  return worldId ? (
    <Recorded key={`${section}/${worldId}`} section={section} worldId={worldId} />
  ) : (
    <p>No run yet. Start a run from Home to see its recorded activity.</p>
  );
}
function Recorded({ section, worldId }: { section: Section; worldId: string }) {
  const client = useClient();
  const sample = useIsFixtureClient();
  const events = useRunLog(client, worldId);
  const done = worldStatus(events) === "completed";
  const [layout, retry] = useAdminRead(
    "load the connections and gates",
    (signal) => client.getLayout(worldId, signal),
    section === "connections",
  );
  const [delivery] = useAdminRead(
    "load the estimate",
    () => client.getDelivery(worldId),
    done && section === "mail",
  );
  const answered = events.filter((event) => event.type === "approval.resolved");
  const open = events.filter(
    (event) =>
      event.type === "approval.requested" &&
      !answered.some((answer) => field(answer, "gate_id") === field(event, "gate_id")),
  );
  const consent = events.filter(
    (event) =>
      event.type === "connection.requested" &&
      !events.some(
        (answer) =>
          (answer.type === "connection.consented" &&
            field(answer, "card_id") === field(event, "card_id")) ||
          (answer.type === "connection.revoked" &&
            answer.seq > event.seq &&
            field(answer, "connector") === field(event, "connector")),
      ),
  );
  let content: ReactNode;
  if (section === "console")
    content = (
      <>
        <p>
          {open.length} questions waiting · {answered.length} answers recorded ·{" "}
          {answered.filter((event) => event.authz?.by === "team_lead").length} by a Team Lead.
        </p>
        <Block title="Questions waiting">
          <Events testid="lead-queue" events={open} empty="No question is waiting." />
          <a href={`/needs-you?world=${encodeURIComponent(worldId)}`}>Review questions</a>
        </Block>
        <Block title="Decision history">
          <Events events={answered} empty="No answer has been recorded yet." />
        </Block>
      </>
    );
  else if (section === "connections")
    content = (
      <>
        <ConnBlock
          title="Run connections"
          line="What this run starts with, and what waits for you."
        >
          {layout.status === "ready" ? (
            <>
              <ul className="park-runconn-list" data-testid="connected-accounts">
                {layout.value.semantic.islands.map((island) => (
                  <li key={island.id} className="park-runconn-row">
                    <span className="park-runconn-name">{island.name}</span>
                    <span className="park-runconn-label">Starting state:</span>
                    <span className={`park-runconn-pill park-runconn-pill--${island.state}`}>
                      {STARTING[island.state]}
                    </span>
                  </li>
                ))}
              </ul>
              <ul className="park-runconn-list">
                {layout.value.semantic.gates.map((gate) => (
                  <li key={gate.id} className="park-runconn-row">
                    <span className="park-runconn-name">{nameOf(gate.guards)}</span>
                    <span
                      className={`park-runconn-pill park-runconn-pill--${gate.policy_ref ? "policy" : "wait"}`}
                    >
                      {gate.policy_ref ? "Policy: runs on its own" : "Waits for you"}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : layout.status === "error" ? (
            <p role="alert" className="park-runconn-empty">
              {layout.message}{" "}
              <button type="button" className="park-runconn-link" onClick={retry}>
                Try again
              </button>
            </p>
          ) : (
            <output className="park-runconn-empty">Loading connections…</output>
          )}
        </ConnBlock>
        <ConnBlock
          title="Waiting for your consent"
          line="Access Tilo asked for that nobody has answered yet."
        >
          {consent.length ? (
            <ul className="park-runconn-list">
              {consent.map((event) => (
                <li key={event.seq} className="park-runconn-row">
                  <span className="park-runconn-name">
                    {nameOf(String(field(event, "connector")))}
                  </span>
                  <span className="park-runconn-label">{event.summary}</span>
                  <a
                    className="park-runconn-link"
                    href={`/needs-you/consent?world=${encodeURIComponent(worldId)}`}
                  >
                    Review
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="park-runconn-empty">No access request is waiting.</p>
          )}
        </ConnBlock>
      </>
    );
  else {
    const transfer = (event: Event, action: string, direction: string) =>
      event.type === "data.transfer" &&
      field(event, "action_type") === action &&
      field(event, "direction") === direction;
    const sends = events.filter(
      (event) =>
        event.type === "approval.requested" && field(event, "action_type") === "send_email",
    );
    const draftIds = new Set(
      sends.map((event) => (field(event, "item") as { artifact_id?: string } | null)?.artifact_id),
    );
    const drafts = events.filter(
      (event) =>
        event.type.startsWith("artifact.") &&
        draftIds.has((field(event, "artifact") as { artifact_id?: string } | null)?.artifact_id),
    );
    const readers = new Map(
      events
        .filter((event) => transfer(event, "read_email", "in"))
        .map((event) => [event.actor, event.seq]),
    );
    const estimate =
      done && delivery.status === "ready" && delivery.value.time_saved
        ? `About ${delivery.value.time_saved.low_min} to ${delivery.value.time_saved.high_min} min saved (estimate)`
        : delivery.status === "error"
          ? delivery.message
          : "No time-saved estimate yet.";
    content = (
      <>
        <Block title="Drafts">
          <Events events={[...drafts, ...sends]} empty="No draft has been written yet." />
        </Block>
        <Block title="Sent">
          <Events
            events={events.filter((event) => transfer(event, "send_email", "out"))}
            empty="Nothing has been sent yet."
          />
        </Block>
        <Block title="Triage">
          <Events
            events={events.filter(
              (event) =>
                !drafts.includes(event) &&
                (transfer(event, "read_email", "in") ||
                  (event.type === "artifact.created" &&
                    event.seq > (readers.get(event.actor) ?? Number.POSITIVE_INFINITY))),
            )}
            empty="No mail has been triaged yet."
          />
        </Block>
        <Block title="Digest">
          <Events
            events={events.filter((event) => event.type === "world.completed")}
            empty="The digest appears when the run finishes."
          />
          <p>
            {estimate} <a href="/settings?section=estimate">How we estimate</a>
          </p>
        </Block>
      </>
    );
  }
  return (
    <div>
      {sample && (
        <p className="park-runconn-sample">Sample recorded run · no live action is shown.</p>
      )}
      {content}
    </div>
  );
}
export const MailSection = () => <RunSection section="mail" />;
export const ConsoleSection = () => <RunSection section="console" />;
export const ConnectionsSection = () => <RunSection section="connections" />;
