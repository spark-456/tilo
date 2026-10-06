// S-17 Email Autopilot home (PRD 18.3, 11.2 to 11.4): triage, drafts, sent and digest. Each list is
// the recorded events of the run, so nothing appears before it happened (HR-1); mail content is
// never shown, only Tilo's own one-line summaries. Events are told apart by registered fields only
// (data.transfer's action_type and direction, approval.requested's action_type and item, and the
// actor of an artifact), never by a scenario's artifact or connector ids.
// TODO(open question, in the PR body): the contracts have no "mail" category on artifacts or on
// connectors, so a run that reads mail by another action_type name shows empty lists here until
// they define one. Time saved is always an estimate with its method link (PRD 18.4). Mail Room
// appears only as a building name in the design exports: cards and rows after "Tilo Team.dc.html".
import type { Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { waitingForYou } from "../world/runLog";
import { worldStatus } from "../world/runSummary";
import { AppLink } from "./AppLink";
import {
  EventList,
  Page,
  Section,
  Soon,
  Stats,
  doneState,
  field,
  useFixtureRun,
  waitState,
} from "./kit";
import { useRemote } from "./remote";

const transfer = (e: Event, action: string, direction: "in" | "out"): boolean =>
  e.type === "data.transfer" &&
  field(e, "action_type") === action &&
  field(e, "direction") === direction;
const artifactId = (e: Event): string | undefined =>
  (field(e, "artifact") as { artifact_id?: string } | null | undefined)?.artifact_id;

export function S_17() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [saved] = useRemote("load the digest", () => client.getDelivery(worldId));
  const done = worldStatus(events) === "completed"; // the estimate follows the run
  const sendRequests = events.filter(
    (e) => e.type === "approval.requested" && field(e, "action_type") === "send_email",
  );
  // The drafts are the artifacts a send is asked about; the mail readers are the agents that took
  // mail in, and what they made afterwards is the triage.
  const draftIds = new Set(
    sendRequests.map((e) => (field(e, "item") as { artifact_id?: string } | null)?.artifact_id),
  );
  const readers = new Map(
    events.filter((e) => transfer(e, "read_email", "in")).map((e) => [e.actor, e.seq]),
  );
  const isDraft = (e: Event) => e.type.startsWith("artifact.") && draftIds.has(artifactId(e));
  const isTriage = (e: Event) =>
    transfer(e, "read_email", "in") ||
    (e.type === "artifact.created" && e.seq > (readers.get(e.actor) ?? Number.POSITIVE_INFINITY));
  const drafts = events.filter(isDraft);
  const sent = events.filter((e) => transfer(e, "send_email", "out"));
  const waiting = waitingForYou(events);
  const written = drafts.filter((e) => e.type === "artifact.created").length;
  const list = (keep: (e: Event) => boolean, empty: string) => (
    <EventList events={events.filter(keep)} all={events} empty={empty} />
  );
  return (
    <Page
      testid="mail"
      title="Email Autopilot"
      sub="Tilo sorts your mail, drafts replies in your style and sends them only as you allow."
    >
      <Stats
        items={[
          ["Waiting for you", waiting, waitState(waiting)],
          ["Drafts written", written, doneState(written, "Written")],
          ["Replies sent", sent.length, doneState(sent.length, "Sent")],
        ]}
      />
      <Section
        title="Drafts"
        note="Every reply waits for you unless one of your rules covers it."
        reserve={[8, 10]}
        action={<Soon labels={["Edit my style profile"]} />}
      >
        {list((e) => isDraft(e) || sendRequests.includes(e), "No draft has been written yet.")}
      </Section>
      <Section title="Sent" note="Replies stay in their thread." reserve={4}>
        {list((e) => sent.includes(e), "Nothing has been sent yet.")}
      </Section>
      <Section
        title="Triage"
        note="What came in, and what the agents made of it."
        reserve={[6, 7]}
        action={<Soon labels={["Add a VIP sender"]} />}
      >
        {list((e) => isTriage(e) && !isDraft(e), "No mail has been triaged yet.")}
      </Section>
      <Section title="Digest" reserve={6}>
        {list((e) => e.type === "world.completed", "The digest appears when the run finishes.")}
        <p data-testid="time-saved">
          {done && saved.status === "ready" && saved.value.time_saved ? (
            <>
              About {saved.value.time_saved.low_min} to {saved.value.time_saved.high_min} min saved
              (estimate) ·{" "}
              <AppLink to="/estimate" className="tile-link">
                How we estimate
              </AppLink>
            </>
          ) : done && saved.status === "error" ? (
            saved.message
          ) : (
            "No time-saved estimate yet."
          )}
        </p>
      </Section>
    </Page>
  );
}
