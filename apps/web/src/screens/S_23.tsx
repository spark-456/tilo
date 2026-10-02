// S-23 How we estimate; status page (PRD 18.3, 14.2, 14.3, 18.4). The two one-sentence methods are
// the PRD's, word for word, because every estimate in the app links here. The example is the
// fixture run's figures from client.getDelivery, always marked an estimate, and shown only once
// world.completed is recorded (the same gate as S-17: no figure before its event). The status
// block says only what is true of this build: it serves recorded data and no live service is
// connected. design/source "Tilo 2 Balanced Refined.dc.html" 2-3 only links here, so: cards and
// rows after "Tilo Team.dc.html", neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { FIXTURE_APPROACHES } from "../api/fixtures/derived";
import { worldStatus } from "../world/runSummary";
import { Chip, Page, Row, Section, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

export function S_23() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [delivery] = useRemote("load the example", () => client.getDelivery(worldId));
  const done = worldStatus(events) === "completed";
  return (
    <Page
      testid="estimate"
      title="How we estimate"
      sub="Every time or credit figure in Tilo is marked as an estimate and links here."
    >
      <Section
        title="Time saved (estimate)"
        note="Failed or unverified units count as zero, and the range comes from the 25th and 75th percentiles."
      >
        <p>
          We count the units of work the agents finished, multiply by the minutes a person took for
          the same unit in our timing study, and subtract the minutes you spent steering and
          reviewing.
        </p>
      </Section>
      <Section title="Credits saved">
        <p>
          When Tilo reuses a result, we credit what that result actually cost the first time, minus
          the cost of the lookup. We never count what another approach might have cost. One credit
          is US${FIXTURE_APPROACHES.credit_usd} at standard list prices.
        </p>
      </Section>
      <Section title="Example from the recorded run" reserve={3}>
        <p data-testid="estimate-example">
          {done && delivery.status === "ready" && delivery.value.time_saved
            ? `About ${delivery.value.time_saved.low_min} to ${delivery.value.time_saved.high_min} min saved (estimate) for ${delivery.value.credits_used} credits.`
            : "The example appears when the recorded run finishes."}
        </p>
      </Section>
      <Section title="Status" note="What is true of this build, right now.">
        <ul className="blist" data-testid="status-rows">
          <Row name="This app" sub="You are using it." state={<Chip tone="done">Running</Chip>} />
          <Row
            name="Run data"
            sub="Recorded fixtures, not a live run."
            state={<Chip tone="fyi">Recorded</Chip>}
          />
          <Row
            name="Live services"
            sub="No live service is connected in this build, so there is no live status to show."
            state={<Chip tone="soon">Not connected</Chip>}
          />
        </ul>
      </Section>
    </Page>
  );
}
