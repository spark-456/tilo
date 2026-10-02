import { memo } from "react";
import { useIsFixtureClient } from "./api/ClientProvider";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { usePathname } from "./router";
import { FlowShell } from "./screens/FlowShell";
import { PrimaryNav } from "./screens/PrimaryNav";
import { matchScreen } from "./screens/routes";
import { Stage } from "./stage/Stage";
import { useWorldFixture } from "./world/useWorldFixture";

// Stage mode is a display setting (PRD 9.6).
// Memoised so each applied event adds one row instead of re-rendering the whole list.
const TraceRow = memo(({ seq, type }: { seq: number; type: string }) => (
  <li data-testid="trace-row" data-seq={seq} data-event-type={type}>
    {seq} {type}
  </li>
));
const stageMode = new URLSearchParams(window.location.search).get("display") === "stage";

/** PRD 18.3 layout frame: desktop rails either side of the stage; mobile bottom tabs. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  const world = useWorldFixture();
  const fixtureClient = useIsFixtureClient();
  const screen = matchScreen(usePathname()); // null: the stage and the flow shell
  return (
    <div className="app-shell" data-stage-mode={stageMode ? "on" : "off"}>
      {!mobile && <PrimaryNav id="left-rail" mobile={false} />}
      {screen ? (
        <main className="screen-page" data-testid="screen-page" data-screen={screen.id}>
          <screen.Component params={screen.params} />
        </main>
      ) : (
        <Stage {...(world.active ? { onWorld: world.onWorld, seq: world.seq } : {})} />
      )}
      {!screen && !world.active && <FlowShell />}
      {(world.active || fixtureClient) && (
        // HR-4/BQ-07: permanent (fixture mode, and whenever the fixture client is active), never
        // dismissable, exposed to assistive tech; fixed so no layout (mobile bottom tabs,
        // stage-mode scale) can ever cover or push it off-screen.
        // biome-ignore lint/a11y/useSemanticElements: <output> is for a form/calculation result; this is a persistent mode banner, so an explicit role="status" region fits better.
        <div className="fixture-replay-banner" data-testid="fixture-replay-banner" role="status">
          Fixture replay — dev data, not a real run
        </div>
      )}
      {world.loadError && (
        <div className="fixture-load-alert" role="alert">
          {world.loadError}
        </div>
      )}
      {world.active && world.speedLabel && (
        <div className="speed-badge" data-testid="speed-badge">
          {world.speedLabel}
        </div>
      )}
      {mobile ? (
        <PrimaryNav id="bottom-tabs" mobile />
      ) : (
        <aside className="right-rail" data-testid="right-rail">
          <h2>Activity</h2>
          <p data-testid="right-rail-meter">Nothing yet. This fills in once a run starts.</p>
          <h2>Needs you</h2>
          <p>Nothing needs you.</p>
          <h2>Roster</h2>
          <p>No agents assigned.</p>
          {world.active && (
            <>
              <h2>Trace</h2>
              <ul className="trace-list" data-testid="trace-list">
                {world.trace.map((row) => (
                  <TraceRow key={row.seq} seq={row.seq} type={row.type} />
                ))}
              </ul>
            </>
          )}
        </aside>
      )}
    </div>
  );
}
