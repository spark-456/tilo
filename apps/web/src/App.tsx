import { memo, useEffect, useRef } from "react";
import { useIsFixtureClient, useReplaySpeed } from "./api/ClientProvider";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { NeedsYouRail } from "./needs-you/NeedsYouRail";
import { matchFlowRoute, usePathname } from "./router";
import { FlowShell } from "./screens/FlowShell";
import { PrimaryNav } from "./screens/PrimaryNav";
import { WorldPanels } from "./screens/WorldPanels";
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
const WORLD_SCREENS: ReadonlySet<string> = new Set(["S-05", "S-10", "S-11", "S-12"]);
/** Screens outside a world address that still read the replayed run (AGW-08 group B): HR-6 applies. */
const RUN_SCREENS: ReadonlySet<string> = new Set([
  "S-06",
  "S-07",
  "S-13",
  "S-14",
  "S-15",
  "S-16",
  "S-17",
  "S-18",
  "S-19",
  "S-21",
  "S-23",
]);
const stageMode = new URLSearchParams(window.location.search).get("display") === "stage";

/** PRD 18.3 layout frame: desktop rails either side of the stage; mobile bottom tabs. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  const world = useWorldFixture();
  const fixtureClient = useIsFixtureClient();
  const replaySpeed = useReplaySpeed();
  const path = usePathname();
  const screen = matchScreen(path); // null: the stage and the flow shell
  const previousPath = useRef(path);
  // After a route change a full-page screen's heading takes focus, so keyboard and screen-reader
  // users keep their place (the flow shell does the same for its own heading).
  useEffect(() => {
    if (previousPath.current === path) return; // not the first render, nor StrictMode's second effect
    previousPath.current = path;
    const h1 = document.querySelector<HTMLElement>(".screen-page h1");
    h1?.setAttribute("tabindex", "-1");
    h1?.focus();
  }, [path]);
  // The world a path belongs to: its S-04 panels fill the right rail on every world screen (S-04,
  // S-05, S-10, S-11, S-12) and, on mobile, a bottom sheet on S-04 itself.
  const flow = matchFlowRoute(path);
  const worldId = screen
    ? WORLD_SCREENS.has(screen.id)
      ? (screen.params[0] ?? null)
      : null
    : flow.screen === "World"
      ? flow.worldId
      : null;
  const hudWorld = screen ? null : worldId;
  return (
    <div className="app-shell" data-stage-mode={stageMode ? "on" : "off"}>
      {!mobile && <PrimaryNav id="left-rail" mobile={false} />}
      {screen ? (
        <main className="screen-page" data-testid="screen-page" data-screen={screen.id}>
          <screen.Component
            key={`${screen.id}:${screen.params.join("/")}`}
            params={screen.params}
          />
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
      {(worldId || (screen && RUN_SCREENS.has(screen.id))) &&
        replaySpeed !== 1 &&
        !world.active && (
          // HR-6: a replay that is not at its recorded pace always says so, on every world screen and
          // after lens navigation drops ?speed (the client keeps its speed).
          <div className="speed-badge client-speed" data-testid="speed-badge">
            {replaySpeed}×
          </div>
        )}
      {mobile ? (
        <>
          {hudWorld && (
            <details
              className="hud-sheet"
              onKeyDown={(e) => {
                if (e.key === "Escape") e.currentTarget.open = false;
              }}
            >
              <summary>World status</summary>
              <WorldPanels key={hudWorld} worldId={hudWorld} />
            </details>
          )}
          <PrimaryNav id="bottom-tabs" mobile />
        </>
      ) : (
        <aside className="right-rail" data-testid="right-rail">
          {worldId ? (
            <WorldPanels key={worldId} worldId={worldId} tabs={hudWorld !== null} />
          ) : (
            <>
              <h2>Activity</h2>
              <p data-testid="right-rail-meter">Nothing yet. This fills in once a run starts.</p>
              {screen && RUN_SCREENS.has(screen.id) ? (
                <NeedsYouRail />
              ) : (
                <>
                  <h2>Needs you</h2>
                  <p>Nothing needs you.</p>
                </>
              )}
              <h2>Roster</h2>
              <p>No agents assigned.</p>
            </>
          )}
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
