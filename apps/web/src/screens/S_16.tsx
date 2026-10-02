// S-16 Channels (PRD 18.3, 11.1): WhatsApp binding, email and notification preferences. Binding
// and preferences are placeholders; what is real is the state of the world's channel islands (from
// client.getLayout) and the channel messages recorded in the run. No design export covers this
// screen: cards and rows after "Tilo Team.dc.html", neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { Loaded } from "./FlowShell";
import { Chip, EventList, Page, Row, Section, Soon, field, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

const ISLAND_STATE = {
  locked: ["Not connected", "blocked"],
  requested: ["Waiting for your consent", "needs"],
  connected: ["Connected", "done"],
  failed: ["Access lost", "blocked"],
} as const;

export function S_16() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the channels", () => client.getLayout(worldId));
  const messages = events.filter((e) => e.type.startsWith("channel."));
  return (
    <Page
      testid="channels"
      title="Channels"
      sub="Where Tilo reaches you, and where you can answer it from."
    >
      <Soon
        labels={[
          "Bind a WhatsApp number",
          "Change notification email",
          "Choose channels",
          "Set quiet hours",
        ]}
      />
      <Section
        title="WhatsApp"
        note="You bind your number with a one-time code sent over WhatsApp, and confirm it again every 30 days. Tilo understands STOP AUTOPILOT, PAUSE and UNSUBSCRIBE."
        reserve={4}
      >
        <Loaded what="the channels" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => (
            <ul className="rows" data-testid="channel-islands">
              {l.semantic.islands
                .filter((i) => i.conn === "channel")
                .map((i) => (
                  <Row
                    key={i.id}
                    name={i.name}
                    sub={`${words(i.conn)} in this world`}
                    state={<Chip tone={ISLAND_STATE[i.state][1]}>{ISLAND_STATE[i.state][0]}</Chip>}
                  />
                ))}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section
        title="Email"
        note="Notifications, digests and question cards come from Tilo's sending domain, with a signed link to answer."
      >
        <p className="empty-note">Notification preferences will be set here.</p>
      </Section>
      <Section title="Recent channel messages" reserve={7}>
        <EventList
          events={messages}
          all={events}
          empty="No channel message has been recorded yet."
          extra={(e) => <Chip tone="fyi">{words(String(field(e, "channel")))}</Chip>}
        />
      </Section>
    </Page>
  );
}
