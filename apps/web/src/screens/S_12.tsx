// S-12 Delivery and celebration (PRD 18.3, 18.4 estimate copy, UX-5). Layout after design/source
// "Tilo 2 Balanced Refined.dc.html" 2-3: a finished header, stat tiles, the one primary button,
// then the deliverables and a row of next actions. The finished state, the tick and the totals
// appear only once the run log holds world.completed (HR-1); before that the screen says the run
// is not finished. Credits come from the same events as the rail. The mark is still, no motion
// (HR-2); time saved is always marked an estimate and linked beside the figure (PRD 18.4).
import { useClient } from "../api/ClientProvider";
import { creditsUsed, useRunLog } from "../world/runLog";
import { worldStatus } from "../world/runSummary";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { EmptyState } from "./kit";
import { useAction, useRemote } from "./remote";
import type { ScreenProps } from "./routes";

const ACTIONS = ["Share", "Run again", "Make recurring", "Save as skill", "Download"];

export function S_12({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const client = useClient();
  const events = useRunLog(client, worldId);
  const finished = worldStatus(events) === "completed";
  // Asked for only once world.completed is recorded: before that the server refuses (409) and the
  // browser logs each refusal as an error.
  const [remote] = useRemote("load the delivery", () => client.getDelivery(worldId), finished);
  const again = useAction("start a new task", async () => "/");
  const delivery = remote.status === "ready" && finished ? remote.value : null;
  return (
    <div className="screen-body wide delivery-slot" data-testid="delivery">
      <h1>Delivery</h1>
      {!finished && (
        <div className="flow-slot">
          <EmptyState
            testid="delivery-pending"
            title="Nothing to deliver yet"
            line="This run has not finished yet. The delivery appears here once it completes."
            action={{ label: "Back to the world", to: `/world/${encodeURIComponent(worldId)}` }}
          />
        </div>
      )}
      {finished && (
        <Loaded
          what="the delivery"
          remote={remote}
          isEmpty={(d) => d.artifacts.length === 0}
          empty={
            <p data-testid="delivery-none">
              This run finished, but none of its steps produced anything to deliver. Nothing is
              missing from your screen.
            </p>
          }
        >
          {(d) => (
            <>
              <p className="flow-summary delivery-done">
                <span aria-hidden="true">&#10003; </span>
                Finished: {d.artifacts.length}{" "}
                {d.artifacts.length === 1 ? "deliverable is" : "deliverables are"} ready.
              </p>
              <ul className="stat-tiles three">
                <li>
                  <span className="stat-name">Time saved</span>
                  <b>
                    {d.time_saved
                      ? `About ${d.time_saved.low_min} to ${d.time_saved.high_min} min`
                      : "No estimate"}
                  </b>
                  <span>
                    estimate ·{" "}
                    <AppLink className="tile-link" to="/estimate">
                      How we estimate
                    </AppLink>
                  </span>
                </li>
                <li>
                  <span className="stat-name">Credits used</span>
                  <b>{creditsUsed(events)}</b>
                </li>
                <li>
                  <span className="stat-name">Deliverables</span>
                  <b>{d.artifacts.length}</b>
                </li>
              </ul>
            </>
          )}
        </Loaded>
      )}
      <Primary label="New task" action={again} />
      {delivery && (
        <>
          <h2>What you got</h2>
          <ul className="stat-tiles">
            {delivery.artifacts.map((a) => (
              <li key={a.id}>
                <b>{a.title}</b>
                <span>
                  {a.kind}, version {a.version}
                </span>
              </li>
            ))}
          </ul>
          <div className="action-row compact">
            {ACTIONS.map((label) => (
              <Placeholder key={label} label={label} compact />
            ))}
          </div>
          <p className="screen-tag">These actions are coming soon.</p>
        </>
      )}
    </div>
  );
}
