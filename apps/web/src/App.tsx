import { memo, useEffect, useRef } from "react";
import { useClient, useIsFixtureClient, useReplaySpeed, useWorldKnown } from "./api/ClientProvider";
import { FIXTURE_WORLD_ID } from "./api/fixtures/derived";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { NeedsYouRail } from "./needs-you/NeedsYouRail";
import { matchFlowRoute, usePathname } from "./router";
import { FlowShell } from "./screens/FlowShell";
import { NotFound } from "./screens/NotFound";
import { ReplayPauseSlot } from "./screens/PauseSlot";
import { PrimaryNav } from "./screens/PrimaryNav";
import { LoggedScrubber, ReplayScrubber } from "./screens/ReplayScrubber";
import { WorldPanels } from "./screens/WorldPanels";
import { type ScreenMatch, matchScreen } from "./screens/routes";
import { Stage } from "./stage/Stage";
import { useRunStatus } from "./world/runLog";
import { speedBadgeText } from "./world/speed";
import { useWorldFixture } from "./world/useWorldFixture";

// Stage mode is a display setting (PRD 9.6).
// Memoised so each applied event adds one row instead of re-rendering the whole list.
const TraceRow = memo(({ seq, type }: { seq: number; type: string }) => (
  <li data-testid="trace-row" data-seq={seq} data-event-type={type}>
    {seq} {type}
  </li>
));
/** The rail's Trace list holds the newest rows only: thousands of list items made a scrub across a
 * long run cost hundreds of ms (FR-WLD-08). The Trace lens lists every event. */
const TRACE_ROWS = 250;
const WORLD_SCREENS: ReadonlySet<string> = new Set(["S-05", "S-10", "S-11", "S-12"]);
/** Screens outside a world address that still read the replayed run (AGW-08 group B): HR-6 applies,
 * and the right rail describes that same run (the fixture world, the only one the client has). */
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
/** The Needs-you screens keep their own rail (the cards queue); the badge still applies to them. */
const NEEDS_YOU_SCREENS: ReadonlySet<string> = new Set(["S-06", "S-07"]);
const NOT_FOUND: ScreenMatch = { id: "not-found", params: [], Component: NotFound };
const stageMode = new URLSearchParams(window.location.search).get("display") === "stage";

/** PRD 18.3 layout frame: desktop rails either side of the stage; mobile bottom tabs. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  const world = useWorldFixture();
  const fixtureClient = useIsFixtureClient();
  const client = useClient();
  const replaySpeed = useReplaySpeed();
  const path = usePathname();
  const matched = matchScreen(path); // null: the stage and the flow shell
  const previousPath = useRef(path);
  // After a route change a full-page screen's heading takes focus, so keyboard and screen-reader
  // users keep their place (the flow shell does the same for its own heading).
  useEffect(() => {
    if (previousPath.current === path) return; // not the first render, nor StrictMode's second effect
    previousPath.current = path;
    // The World lens is the stage with the flow shell's heading, so it takes focus the same way.
    const h1 = document.querySelector<HTMLElement>(".screen-page h1, .flow-heading");
    h1?.setAttribute("tabindex", "-1");
    h1?.focus();
  }, [path]);
  // The world a path belongs to: its S-04 panels fill the right rail on every world screen (S-04,
  // S-05, S-10, S-11, S-12) and, on mobile, a bottom sheet on S-04 itself.
  const flow = matchFlowRoute(path);
  const pathWorld = matched
    ? WORLD_SCREENS.has(matched.id)
      ? (matched.params[0] ?? null)
      : null
    : flow.screen === "World"
      ? flow.worldId
      : null;
  // A world id the client does not know is "Not found", never another world's run in its place.
  const unknownWorld = !useWorldKnown(pathWorld) && !world.active;
  const screen = unknownWorld ? NOT_FOUND : matched;
  const worldId = unknownWorld ? null : pathWorld;
  const hudWorld = screen ? null : worldId;
  // FR-WLD-07: the stage is veiled only while the recorded run status is "paused" (HR-1).
  const clientStatus = useRunStatus(client, hudWorld);
  const stagePaused = (world.active ? world.status : clientStatus) === "paused";
  const runScreen = screen !== null && RUN_SCREENS.has(screen.id);
  const needsYouScreen = screen !== null && NEEDS_YOU_SCREENS.has(screen.id);
  const railWorld = worldId ?? (runScreen && !needsYouScreen ? FIXTURE_WORLD_ID : null);
  // HR-6: a replay that is not at its recorded pace always says so (after lens navigation drops
  // ?speed the client keeps its speed), in words, in a status region.
  const speedBadge = world.active
    ? world.speedLabel
    : worldId !== null || runScreen
      ? speedBadgeText(replaySpeed)
      : null;
  // FR-WLD-08: the Replay region (scrub + HR-4 banner) on every world route and in fixture mode:
  // in the right rail on desktop, in the column above the tabs on mobile.
  const dock = world.active ? (
    <ReplayScrubber
      worldId={world.worldId}
      events={world.events}
      finished={world.finished}
      fixture
    />
  ) : worldId !== null ? (
    <LoggedScrubber worldId={worldId} fixture={fixtureClient} />
  ) : null;
  return (
    <div
      className="app-shell"
      data-stage-mode={stageMode ? "on" : "off"}
      data-replay-badge={speedBadge ? "on" : "off"}
      data-replay-dock={dock ? "on" : "off"}
    >
      {!mobile && <PrimaryNav id="left-rail" mobile={false} />}
      {screen ? (
        <main className="screen-page" data-testid="screen-page" data-screen={screen.id}>
          <screen.Component
            key={`${screen.id}:${screen.params.join("/")}`}
            params={screen.params}
          />
        </main>
      ) : (
        <Stage
          {...(world.active
            ? { onWorld: world.onWorld, seq: world.seq, selected: world.selected }
            : {})}
          paused={stagePaused}
        />
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
      {speedBadge && (
        // biome-ignore lint/a11y/useSemanticElements: same persistent status region as the banner above, not a form result.
        <div className="speed-badge" data-testid="speed-badge" role="status">
          {speedBadge}
        </div>
      )}
      {mobile ? (
        <>
          {dock}
          {hudWorld && (
            <details
              className="hud-sheet"
              onKeyDown={(e) => {
                if (e.key !== "Escape") return;
                // Closing the sheet hides the focused control, so focus goes back to its summary.
                e.currentTarget.open = false;
                e.currentTarget.querySelector("summary")?.focus();
              }}
            >
              <summary>World status{clientStatus === "paused" ? " · Paused" : ""}</summary>
              <WorldPanels key={hudWorld} worldId={hudWorld} />
            </details>
          )}
          <PrimaryNav id="bottom-tabs" mobile />
        </>
      ) : (
        <aside className="right-rail" data-testid="right-rail">
          {dock}
          {railWorld ? (
            <WorldPanels key={railWorld} worldId={railWorld} tabs={hudWorld !== null} />
          ) : (
            <>
              {world.active && <ReplayPauseSlot status={world.status} />}
              <h2>Activity</h2>
              <p data-testid="right-rail-meter">Nothing yet. This fills in once a run starts.</p>
              {needsYouScreen ? (
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
                {world.trace.length > TRACE_ROWS && (
                  <li>
                    Showing the latest {TRACE_ROWS} of {world.trace.length} events.
                  </li>
                )}
                {world.trace.slice(-TRACE_ROWS).map((row) => (
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
