// S-17 Email Autopilot home (PRD 18.3, 11.2 to 11.4): triage, drafts, sent and digest. Each list is
// the recorded events of the run, so nothing appears before it happened (HR-1); mail content is
// never shown, only Tilo's own one-line summaries. Time saved is always an estimate with its
// method link (PRD 18.4). Mail Room appears only as a building name in the design exports, so
// this uses cards and rows after "Tilo Team.dc.html" and neutral role tokens.
import type { Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { waitingForYou } from "../world/runLog";
import { AppLink } from "./AppLink";
import { EventList, Page, Section, Soon, Stats, field, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

const gmail = (e: Event, direction: string): boolean =>
  e.type === "data.transfer" &&
  field(e, "connector") === "gmail" &&
  field(e, "direction") === direction;
const draft = (e: Event): boolean =>
  e.target === "art_reply_draft" && e.type.startsWith("artifact.");

export function S_17() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [saved] = useRemote("load the digest", () => client.getDelivery(worldId));
  const done = events.some((e) => e.type === "world.completed"); // the estimate follows the run
  const pick = (keep: (e: Event) => boolean) => events.filter(keep);
  const drafts = pick((e) => e.type === "artifact.created" && e.target === "art_reply_draft");
  const sent = pick((e) => gmail(e, "out"));
  const list = (keep: (e: Event) => boolean, empty: string) => (
    <EventList events={pick(keep)} all={events} empty={empty} />
  );
  return (
    <Page
      testid="mail"
      title="Email Autopilot home"
      sub="Tilo sorts your mail, drafts replies in your style and sends them only as you allow."
    >
      <Soon labels={["Edit my style profile", "Add a VIP sender"]} />
      <Stats
        items={[
          ["Waiting for you", waitingForYou(events)],
          ["Drafts written", drafts.length],
          ["Replies sent", sent.length],
        ]}
      />
      <Section
        title="Triage"
        note="Needs a reply, needs an action, FYI, newsletter, suspicious."
        reserve={[6, 7]}
      >
        {list(
          (e) =>
            gmail(e, "in") || (e.type === "artifact.created" && e.target === "art_triage_list"),
          "No mail has been triaged yet.",
        )}
      </Section>
      <Section
        title="Drafts"
        note="Every reply waits for you unless one of your rules covers it."
        reserve={[8, 10]}
      >
        {list((e) => draft(e) || e.type === "approval.requested", "No draft has been written yet.")}
      </Section>
      <Section title="Sent" note="Replies stay in their thread." reserve={4}>
        {list((e) => gmail(e, "out"), "Nothing has been sent yet.")}
      </Section>
      <Section title="Digest" reserve={7}>
        {list((e) => e.type === "world.completed", "The digest appears when the run finishes.")}
        <p data-testid="time-saved">
          {done && saved.status === "ready" && saved.value.time_saved ? (
            <>
              About {saved.value.time_saved.low_min} to {saved.value.time_saved.high_min} min saved
              (estimate) · <AppLink to="/estimate">How we estimate</AppLink>
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
