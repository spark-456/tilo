// S-18 Team Lead console (PRD 18.3, 10.5): the questions waiting, the decision history and answer
// stats. The queue is client.listCards; history is the recorded approval.resolved events. Which
// domain a card is routed to is not in the fixture cards, so every open card is listed. Answering
// belongs to the Needs-you screen (S-06), so each card links there. "Promote to skill" is a Should
// feature: a placeholder. design/source "Tilo Team.dc.html" is org admin, not this view: its card
// and row language, neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Chip, EventList, Page, Row, Section, Soon, Stats, authzText, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

const KIND = { needs_you: "Question", gate: "Approval", consent: "Access", meeting: "Meeting" };

export function S_18() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [cards, retry] = useRemote("load the questions", () => client.listCards(worldId));
  const answered = events.filter((e) => e.type === "approval.resolved");
  const byLead = answered.filter((e) => e.authz?.by === "team_lead").length;
  return (
    <Page
      testid="team-lead"
      title="Team Lead console"
      sub="Questions that need an expert, the answers given so far, and how fast they came."
    >
      <Soon labels={["Promote an answer to a skill"]} />
      <Stats
        items={[
          ["Questions waiting", cards.status === "ready" ? cards.value.length : "-"],
          ["Answers recorded", answered.length],
          ["Answered by a Team Lead", byLead],
        ]}
      />
      <Section
        title="Questions waiting"
        note="Open cards. Answer them on the Needs-you screen."
        reserve={[15, 38]}
      >
        <Loaded what="the questions" remote={cards} retry={retry} isEmpty={(c) => c.length === 0}>
          {(list) => (
            <ul className="rows" data-testid="lead-queue">
              {list.map((c) => (
                <Row
                  key={`${c.id}:${c.rung}:${c.what_happened}`}
                  name={c.what_happened}
                  sub={c.why_it_matters}
                  state={<Chip tone="needs">{KIND[c.kind]}</Chip>}
                >
                  <AppLink to="/needs-you" className="pill">
                    Open
                  </AppLink>
                </Row>
              ))}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section title="Decision history" reserve={4}>
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
            : `${byLead} answer(s) by a Team Lead.`}
        </p>
      </Section>
    </Page>
  );
}
