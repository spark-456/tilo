import { useClient } from "../api/ClientProvider";
import { Loaded } from "./FlowShell";
import { EventList, Page, Row, Section, Soon, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

export function S_09() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [cards, retry] = useRemote("load the meeting card", () => client.listCards(worldId));

  const meetingEvents = events.filter((e) => e.type.startsWith("meeting."));

  return (
    <Page
      testid="meeting"
      title="Meeting"
      sub="Live notes, decisions and actions as they are recorded."
      action={<Soon labels={["Join meeting", "Delegate", "Answer async"]} />}
    >
      <Section
        title="Recording and transcription"
        note="Consent banner is visible whenever recording/transcription is active. Screen works in notes-only mode when audio is declined."
        action={<Soon labels={["Decline audio", "Accept recording"]} />}
      >
        <p className="empty-note">
          Consent banner is visible whenever recording/transcription is active.
        </p>
      </Section>

      <Section title="Meeting purpose" reserve={[5, 5]}>
        <Loaded what="the meeting card" remote={cards} retry={retry} isEmpty={() => false}>
          {(cs) => {
            const meeting = cs.find((c) => c.kind === "meeting");
            if (!meeting) {
              return <p className="empty-note">No meeting has been requested yet.</p>;
            }
            return (
              <ul className="blist">
                <Row name="What happened" sub={meeting.what_happened} />
                <Row name="Why it matters" sub={meeting.why_it_matters} />
              </ul>
            );
          }}
        </Loaded>
      </Section>

      <Section title="Live notes and decisions" reserve={[10, 15]} action={<Soon labels={["Add note"]} />}>
        <EventList
          events={meetingEvents}
          all={events}
          empty="No meeting has been recorded in this run."
        />
      </Section>
    </Page>
  );
}
