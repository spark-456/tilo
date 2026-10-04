// S-09 Meeting screen (FR-WLD-09). Derives all figures from this run's recorded events (HR-1,
// HR-5): a meeting.called event names the card that describes the purpose; if no such event exists
// the purpose section is honestly empty. Events are filtered by both type prefix and run id so
// data from a prior run or a contract fixture card never appears here.
import type { MeetingCalledData } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { Loaded } from "./FlowShell";
import { EventList, Page, Section, Soon, field, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

export function S_09() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [cards, retry] = useRemote("load the meeting card", () => client.listCards(worldId));

  // Derive the run id from this run's events; filter all events by that run id.
  const runId = events[0]?.run_id ?? null;
  const runEvents = runId ? events.filter((e) => e.run_id === runId) : events;

  const meetingEvents = runEvents.filter((e) => e.type.startsWith("meeting."));

  // Purpose comes ONLY from this run's meeting.called events — never from listCards directly.
  const calledEvent = meetingEvents.find((e) => e.type === "meeting.called");
  const calledCardId = calledEvent
    ? (field(calledEvent, "card_id") as string | undefined)
    : undefined;

  return (
    <Page
      testid="meeting"
      title="Meeting"
      sub="Live notes, decisions and actions as they are recorded."
      action={<Soon labels={["Join meeting", "Delegate", "Answer async"]} />}
    >
      <Section title="Meeting purpose" reserve={[5, 5]}>
        {calledCardId ? (
          <Loaded what="the meeting card" remote={cards} retry={retry} isEmpty={() => false}>
            {(cs) => {
              const meeting = cs.find((c) => c.id === calledCardId && c.kind === "meeting");
              if (!meeting) {
                return <p className="empty-note">No meeting has been requested yet.</p>;
              }
              return (
                <ul className="blist">
                  <li className="bitem">
                    <div className="bitem-main">
                      <b>{meeting.what_happened}</b>
                    </div>
                  </li>
                  <li className="bitem">
                    <div className="bitem-main">
                      <span className="bitem-sub">{meeting.why_it_matters}</span>
                    </div>
                  </li>
                </ul>
              );
            }}
          </Loaded>
        ) : (
          <p className="empty-note">No meeting has been requested yet.</p>
        )}
      </Section>

      <Section
        title="Live notes and decisions"
        reserve={[10, 15]}
        action={<Soon labels={["Add note"]} />}
      >
        <EventList
          events={meetingEvents}
          all={runEvents}
          empty="No meeting has been recorded in this run."
        />
      </Section>
    </Page>
  );
}
