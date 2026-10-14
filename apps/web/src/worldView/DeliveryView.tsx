// Delivery and celebration (PRD 18.3, 18.4 estimate copy, UX-5): a finished header, stat tiles, the one primary
// button, then the deliverables. The finished state and the totals appear only once the run log holds
// world.completed (HR-1); before that the page says the run is not finished. Credits come from the same events as
// the rail. The mark is still, no motion (HR-2); time saved is always marked an estimate and linked beside the
// figure (PRD 18.4).
import { useClient } from "../api/ClientProvider";
import { navigatePark } from "../park/app/router";
import { Button } from "../park/components";
import { useRemote } from "../screens/remote";
import { creditsUsed, useRunLog } from "../world/runLog";
import { worldStatus } from "../world/runSummary";
import { LensFrame } from "./LensFrame";
import { ViewLink } from "./ViewLink";
import { lensPath } from "./routes";

export function DeliveryView({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const finished = worldStatus(events) === "completed";
  // Asked for only once world.completed is recorded: before that the server refuses (409) and the browser logs
  // each refusal as an error.
  const [remote, retry] = useRemote(
    "load the delivery",
    () => client.getDelivery(worldId),
    finished,
  );
  const delivery = remote.status === "ready" && finished ? remote.value : null;
  return (
    <LensFrame worldId={worldId} current="delivery" title="Delivery">
      <div data-testid="delivery" className="park-view-body">
        {!finished ? (
          <div className="park-view-empty" data-testid="delivery-pending">
            <h2 className="park-view-h2 park-view-empty-title">Nothing to deliver yet</h2>
            <p className="park-view-note">
              This run has not finished yet. The delivery appears here once it completes.
            </p>
            <ViewLink className="park-view-chiplink" to={lensPath(worldId, "stage")}>
              Back to the world
            </ViewLink>
          </div>
        ) : remote.status === "loading" ? (
          <p className="park-view-note">Loading the delivery…</p>
        ) : remote.status === "error" ? (
          <div className="park-view-alert" role="alert">
            <p>{remote.message}</p>
            <button type="button" className="park-view-chiplink" onClick={retry}>
              Try again
            </button>
          </div>
        ) : delivery && delivery.artifacts.length === 0 ? (
          <p className="park-view-note" data-testid="delivery-none">
            This run finished, but none of its steps produced anything to deliver. Nothing is
            missing from your screen.
          </p>
        ) : delivery ? (
          <>
            <p className="park-view-done">
              <span aria-hidden="true">&#10003; </span>
              Finished: {delivery.artifacts.length}{" "}
              {delivery.artifacts.length === 1 ? "deliverable is" : "deliverables are"} ready.
            </p>
            <ul className="park-view-tiles">
              <li>
                <span className="park-view-tilename">Time saved</span>
                <b>
                  {delivery.time_saved
                    ? `About ${delivery.time_saved.low_min} to ${delivery.time_saved.high_min} min`
                    : "No estimate"}
                </b>
                <span>
                  estimate ·{" "}
                  <ViewLink className="park-view-chiplink" to="/estimate">
                    How we estimate
                  </ViewLink>
                </span>
              </li>
              <li>
                <span className="park-view-tilename">Credits used</span>
                <b>{creditsUsed(events)}</b>
              </li>
              <li>
                <span className="park-view-tilename">Deliverables</span>
                <b>{delivery.artifacts.length}</b>
              </li>
            </ul>
            <h2 className="park-view-h2">What you got</h2>
            <ul className="park-view-tiles">
              {delivery.artifacts.map((a) => (
                <li key={a.id}>
                  <b>{a.title}</b>
                  <span>
                    {a.kind}, version {a.version}
                  </span>
                </li>
              ))}
            </ul>
            <p className="park-view-note">
              Sharing, re-running and downloading a delivery are not built yet.
            </p>
          </>
        ) : null}
        <div className="park-view-actions">
          <Button variant="primary" onClick={() => navigatePark("/")}>
            New task
          </Button>
        </div>
      </div>
    </LensFrame>
  );
}
