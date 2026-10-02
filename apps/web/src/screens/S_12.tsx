// S-12 Delivery and celebration (PRD 18.3, 18.4 estimate copy, UX-5). Layout after design/source
// "Tilo 2 Balanced Refined.dc.html" 2-3: a finished header, stat tiles, the deliverables and a
// row of next actions. Everything comes from client.getDelivery. The celebration is a still mark,
// no motion (HR-2); time saved is always marked an estimate and linked (PRD 18.4).
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { useAction, useRemote } from "./remote";
import type { ScreenProps } from "./routes";

export function S_12({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const client = useClient();
  const [remote, retry] = useRemote("load the delivery", () => client.getDelivery(worldId));
  const again = useAction("start a new task", async () => "/");
  return (
    <div className="screen-body wide delivery-slot" data-testid="delivery">
      <h1>Delivery</h1>
      <Loaded
        what="the delivery"
        remote={remote}
        retry={retry}
        isEmpty={(d) => d.artifacts.length === 0}
      >
        {(d) => (
          <>
            <p className="flow-summary delivery-done">
              <span aria-hidden="true">&#10003; </span>
              Finished: {d.artifacts.length}{" "}
              {d.artifacts.length === 1 ? "deliverable is" : "deliverables are"} ready.
            </p>
            <ul className="stat-tiles">
              <li>
                <span className="stat-name">Time saved</span>
                <b>
                  {d.time_saved
                    ? `About ${d.time_saved.low_min} to ${d.time_saved.high_min} min`
                    : "No estimate"}
                </b>
                <span>estimate</span>
              </li>
              <li>
                <span className="stat-name">Credits used</span>
                <b>{d.credits_used}</b>
              </li>
              <li>
                <span className="stat-name">Deliverables</span>
                <b>{d.artifacts.length}</b>
              </li>
            </ul>
            <h2>What you got</h2>
            <ul className="stat-tiles">
              {d.artifacts.map((a) => (
                <li key={a.id}>
                  <b>{a.title}</b>
                  <span>
                    {a.kind}, version {a.version}
                  </span>
                </li>
              ))}
            </ul>
            <div className="action-row">
              <Placeholder label="Share" />
              <Placeholder label="Run again" />
              <Placeholder label="Make recurring" />
              <Placeholder label="Save as skill" />
              <Placeholder label="Download" />
            </div>
            <p>
              <AppLink to="/estimate">How we estimate time saved</AppLink>
            </p>
          </>
        )}
      </Loaded>
      <Primary label="New task" action={again} />
    </div>
  );
}
