// OLD-UI-OUT-4: recorded run logic, presented with Park components (HR-1/HR-7).
import type { Event } from "@tilo/contracts";
import type { ReactNode } from "react";
import { useClient, useIsFixtureClient } from "../../../api/ClientProvider";
import { FIXTURE_APPROACHES } from "../../../api/fixtures/derived";
import { useRemote } from "../../../screens/remote";
import { useRunLog } from "../../../world/runLog";
import { worldStatus } from "../../../world/runSummary";
import { useRunWorld } from "../../../world/worldContext";
import { StopAutopilot } from "./StopAutopilot";
import { Block, nameOf } from "./shared";
import "./Admin.css";

const field = (e: Event, key: string): unknown => (e.data as Record<string, unknown>)[key];
function Events({
  events,
  empty,
  testid,
}: { events: readonly Event[]; empty: string; testid?: string }) {
  return events.length ? (
    <ul data-testid={testid}>
      {events.map((e) => (
        <li key={e.seq}>
          {e.summary}
          {e.authz && (
            <p>
              Authorised by{" "}
              {e.authz.by === "policy"
                ? "Your rule"
                : e.authz.by === "team_lead"
                  ? "A Team Lead"
                  : "You"}{" "}
              · {e.authz.at}
            </p>
          )}
        </li>
      ))}
    </ul>
  ) : (
    <p>{empty}</p>
  );
}
export type RunSection = "autonomy" | "channels" | "estimate";
export function RunSectionView({ section }: { section: RunSection }) {
  const worldId = useRunWorld();
  return (
    <>
      {section === "estimate" && (
        <>
          <Block title="Time saved (estimate)">
            <p>
              We count the units of work the agents finished, multiply by the minutes a person took
              for the same unit in our timing study, and subtract the minutes you spent steering and
              reviewing.
            </p>
            <p>
              Failed or unverified units count as zero, and the range comes from the 25th and 75th
              percentiles.
            </p>
          </Block>
          <Block title="Credits saved">
            <p>
              When Tilo reuses a result, we credit what that result actually cost the first time,
              minus the cost of the lookup. We never count what another approach might have cost.
              One credit is US${FIXTURE_APPROACHES.credit_usd} at standard list prices.
            </p>
          </Block>
        </>
      )}
      {worldId ? (
        <RecordedSection key={`${section}/${worldId}`} section={section} worldId={worldId} />
      ) : (
        <p>No run yet. Start a run from Home to see its recorded activity.</p>
      )}
    </>
  );
}
function RecordedSection({ section, worldId }: { section: RunSection; worldId: string }) {
  const client = useClient();
  const sample = useIsFixtureClient();
  const events = useRunLog(client, worldId);
  const done = worldStatus(events) === "completed";
  const [layout, retry] = useRemote(
    "load the connections and gates",
    (signal) => client.getLayout(worldId, signal),
    ["autonomy", "channels"].includes(section),
  );
  const [delivery] = useRemote(
    "load the estimate",
    () => client.getDelivery(worldId),
    done && section === "estimate",
  );
  const estimate =
    done && delivery.status === "ready" && delivery.value.time_saved
      ? `About ${delivery.value.time_saved.low_min} to ${delivery.value.time_saved.high_min} min saved (estimate)`
      : delivery.status === "error"
        ? delivery.message
        : "The example appears when the recorded run finishes.";
  const connections = (
    <Block title={"Connected Google accounts"}>
      {layout.status === "ready" ? (
        <>
          <ul data-testid="connected-accounts">
            {layout.value.semantic.islands
              .filter((i) => i.conn !== "channel")
              .map((i) => (
                <li key={i.id}>
                  {i.name} · Starting state:{" "}
                  {
                    {
                      connected: "Connected",
                      locked: "Not connected",
                      requested: "Waiting for your consent",
                      failed: "Access lost",
                    }[i.state]
                  }
                </li>
              ))}
          </ul>
          <ul>
            {layout.value.semantic.gates.map((g) => (
              <li key={g.id}>
                {nameOf(g.guards)} · {g.policy_ref ? "Policy: runs on its own" : "Waits for you"}
              </li>
            ))}
          </ul>
        </>
      ) : layout.status === "error" ? (
        <p role="alert">
          {layout.message}{" "}
          <button type="button" onClick={retry}>
            Try again
          </button>
        </p>
      ) : (
        <output>Loading connections…</output>
      )}
    </Block>
  );
  let body: ReactNode = null;
  if (section === "channels")
    body = (
      <>
        {connections}
        <Block title="Email">
          <Events
            events={events.filter(
              (e) =>
                e.type.startsWith("channel.") &&
                ["web", "mobile_web", "email"].includes(String(field(e, "channel"))),
            )}
            empty="No email or in-app message has been recorded yet."
          />
        </Block>
        <Block title="Notification preferences">
          <a href="/profile?tab=notifications">Choose channels and quiet hours</a>
        </Block>
      </>
    );
  else if (section === "autonomy")
    body = (
      <>
        <Block title="Stop all autopilot">
          <StopAutopilot worldId={worldId} />
        </Block>
        <Block title="Levels">
          <p>
            L0 Observe · L1 Ask each time (default) · L2 Instruction is approval · L3 Standing rules
          </p>
        </Block>
        {connections}
        <Block title="Autonomy log">
          <Events
            events={events.filter((e) => e.authz !== null)}
            empty="No authorised action has been recorded yet."
          />
          <a href={`/world/${encodeURIComponent(worldId)}/trace`}>See authorisation in Trace</a>
        </Block>
      </>
    );
  else if (section === "estimate")
    body = (
      <Block title="Example from the recorded run">
        <p>{estimate}</p>
      </Block>
    );
  return (
    <div className="park-admin-sections">
      {sample && <p>Sample recorded run · no live action is shown.</p>}
      {body}
    </div>
  );
}
export const ChannelsSection = () => <RunSectionView section="channels" />;
export const EstimateSection = () => <RunSectionView section="estimate" />;
