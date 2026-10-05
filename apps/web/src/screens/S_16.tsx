// S-16 Channels (PRD 18.3, 11.1; WhatsApp removed by SD-01): email, notification preferences and
// the connected Google accounts. Preferences are placeholders; what is real is the state of the
// world's connections (from client.getLayout, their starting state) and the messages recorded in
// the run that went by email or in the app. `whatsapp` stays a valid contract value but is never
// offered, named or listed here. No design export covers this screen: cards and rows after
// "Tilo Team.dc.html", neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Chip, EventList, Page, Row, Section, Soon, field, nameOf, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

const ISLAND_STATE = {
  locked: ["Not connected", "blocked"],
  requested: ["Waiting for your consent", "needs"],
  connected: ["Connected", "done"],
  failed: ["Access lost", "blocked"],
} as const;

/** Where Tilo's messages can have gone now: the app and email (the contracts hold more values). */
const SHOWN_CHANNELS: ReadonlySet<string> = new Set(["web", "mobile_web", "email"]);

export function S_16() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the channels", (signal) =>
    client.getLayout(worldId, signal),
  );
  const messages = events.filter(
    (e) => e.type.startsWith("channel.") && SHOWN_CHANNELS.has(String(field(e, "channel"))),
  );
  return (
    <Page
      testid="channels"
      title="Channels"
      sub="Where Tilo reaches you, and where you can answer it from."
    >
      <Section
        title="Connected Google accounts"
        note="The Google accounts this world uses, and where each stands. Sign-in and access are reviewed on Connections."
        reserve={5}
        action={
          <AppLink to="/connections" className="pill">
            Review connections
          </AppLink>
        }
      >
        <Loaded what="the accounts" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => (
            <ul className="blist" data-testid="connected-accounts">
              {l.semantic.islands
                .filter((i) => i.conn !== "channel")
                .map((i) => (
                  <Row
                    key={i.id}
                    name={i.name}
                    sub="Starting state of this world"
                    state={<Chip tone={ISLAND_STATE[i.state][1]}>{ISLAND_STATE[i.state][0]}</Chip>}
                  />
                ))}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section title="Recent channel messages" reserve={[3, 4]}>
        <EventList
          events={messages}
          all={events}
          empty="No email or in-app message has been recorded yet."
          extra={(e) => <Chip tone="fyi">{nameOf(String(field(e, "channel")))}</Chip>}
        />
      </Section>
      <Section
        title="Email"
        note="Notifications, digests and question cards come from Tilo's sending domain, with a signed link to answer."
        action={<Soon labels={["Change notification email"]} />}
      />
      <Section title="Notification preferences" note="Choose what reaches you, and where.">
        <Soon labels={["Choose channels", "Set quiet hours"]} />
      </Section>
    </Page>
  );
}
