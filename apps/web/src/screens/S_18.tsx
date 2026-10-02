// S-18 Team Lead console (PRD 18.3, 10.5): the questions waiting, the decision history and answer
// stats. All of it follows this run's recorded events: a question is waiting from its
// approval.requested until an approval.resolved names the same gate, so the count is 0 before the
// request, 1 until the answer and 0 after (the same count as S-15 and S-17). Which Team Lead
// domain a question is routed to is not in the events of this run, so every open question is
// listed. Answering belongs to the Needs-you screen (S-06). "Promote to skill" is a Should
// feature: a placeholder. design/source "Tilo Team.dc.html" is org admin, not this view: its card
// and row language, neutral role tokens.
import { AppLink } from "./AppLink";
import {
  Chip,
  EventList,
  Page,
  Row,
  Section,
  Soon,
  Stats,
  authzText,
  field,
  useFixtureRun,
  words,
} from "./kit";

export function S_18() {
  const { events } = useFixtureRun();
  const answered = events.filter((e) => e.type === "approval.resolved");
  const answeredGates = new Set(answered.map((e) => field(e, "gate_id")));
  const open = events.filter(
    (e) => e.type === "approval.requested" && !answeredGates.has(field(e, "gate_id")),
  );
  const byLead = answered.filter((e) => e.authz?.by === "team_lead").length;
  return (
    <Page
      testid="team-lead"
      title="Team Lead console"
      sub="Questions that need an expert, the answers given so far, and how fast they came."
    >
      <Stats
        items={[
          ["Questions waiting", open.length],
          ["Answers recorded", answered.length],
          ["Answered by a Team Lead", byLead],
        ]}
      />
      <Section
        title="Questions waiting"
        note="Open questions of this run. Answer them on the Needs-you screen."
        reserve={[4, 8]}
      >
        {open.length === 0 ? (
          <p className="empty-note" data-testid="lead-empty">
            No question is waiting.
          </p>
        ) : (
          <ul className="blist" data-testid="lead-queue">
            {open.map((e) => (
              <Row
                key={String(field(e, "card_id"))}
                name={e.summary}
                sub={words(String(field(e, "action_type")))}
                state={<Chip tone="needs">Approval</Chip>}
              >
                <AppLink to="/needs-you" className="pill" aria-label={`Open: ${e.summary}`}>
                  Open
                </AppLink>
              </Row>
            ))}
          </ul>
        )}
      </Section>
      <Section
        title="Decision history"
        reserve={[4, 5]}
        action={<Soon labels={["Promote an answer to a skill"]} />}
      >
        <EventList
          events={answered}
          all={events}
          empty="No answer has been recorded yet."
          extra={(e) => (e.authz ? <Chip tone="done">{authzText(e.authz)}</Chip> : null)}
        />
      </Section>
      <Section title="Answer time" reserve={3}>
        <p className="empty-note" data-testid="lead-stats">
          {byLead === 0
            ? "No Team Lead has answered, so there is no answer time to show."
            : `${byLead} ${byLead === 1 ? "answer" : "answers"} by a Team Lead.`}
        </p>
      </Section>
    </Page>
  );
}
