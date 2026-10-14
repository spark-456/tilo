import { memo, useEffect, useMemo, useRef } from "react";
import { useClient, useIsFixtureClient, useReplaySpeed, useWorldKnown } from "./api/ClientProvider";
import { AssistantPanel } from "./assistant/AssistantPanel";
import { useStageMode } from "./display/stageMode";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { NeedsYouRail } from "./needs-you/NeedsYouRail";
import { isParkOnlyWorld } from "./parkWorlds";
import { matchFlowRoute, usePathname } from "./router";
import { FlowShell } from "./screens/FlowShell";
import { LevelsPanel } from "./screens/LevelsPanel";
import { NotFound } from "./screens/NotFound";
import { ReplayPauseSlot } from "./screens/PauseSlot";
import { PrimaryNav } from "./screens/PrimaryNav";
import { LoggedScrubber, ReplayScrubber } from "./screens/ReplayScrubber";
import { ScreenPage } from "./screens/ScreenPage";
import { StagePresenter } from "./screens/StagePresenter";
import { TopBar } from "./screens/TopBar";
import { HudGlance, WorldPanels } from "./screens/WorldPanels";
import { type ScreenMatch, matchScreen } from "./screens/routes";
import { Stage } from "./stage/Stage";
import { useRunStatus } from "./world/runLog";
import { speedBadgeText } from "./world/speed";
import { useClientWorld } from "./world/useClientWorld";
import { useWorldFixture } from "./world/useWorldFixture";
import { useRunWorld } from "./world/worldContext";

// Stage mode is a display setting (PRD 9.6, FR-WLD-12).
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
  "S-15",
  "S-16",
  "S-17",
  "S-18",
  "S-19",
  "S-23",
]);
/** The Needs-you screens keep their own rail (the cards queue); the badge still applies to them. */
const NEEDS_YOU_SCREENS: ReadonlySet<string> = new Set(["S-06", "S-07"]);
const NOT_FOUND: ScreenMatch = { id: "not-found", params: [], Component: NotFound };

/** PRD 18.3 layout frame: desktop rails either side of the stage; mobile bottom tabs; 1920x1080 stage mode. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  const wideStage = useMediaQuery("(min-width: 1920px)");
  const [stageMode] = useStageMode();
  const stageLayout = stageMode && (wideStage || window.innerWidth >= 1920);
  const world = useWorldFixture();
  const fixtureClient = useIsFixtureClient();
  const client = useClient();
  const runWorld = useRunWorld(); // the remembered run; null with a live API and none (never the fixture)
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
    const focusHeading = (): boolean => {
      const h1 = document.querySelector<HTMLElement>(".screen-page h1, .flow-heading");
      if (!h1 || h1.getClientRects().length === 0) return false; // not there yet, or hidden
      h1.setAttribute("tabindex", "-1");
      h1.focus();
      return true;
    };
    if (focusHeading()) return;
    // A screen is a code-split chunk (NFR-01): its heading arrives with it. Focus it then, unless
    // the person has moved focus somewhere else in the meantime (it is still where the navigation
    // left it: the link they used, or the page body).
    const left = document.activeElement;
    const root = document.getElementById("root") ?? document.body;
    const watch = new MutationObserver(() => {
      if (document.activeElement !== left) return watch.disconnect();
      if (focusHeading()) watch.disconnect();
    });
    watch.observe(root, { childList: true, subtree: true });
    const giveUp = setTimeout(() => watch.disconnect(), 10_000);
    return () => {
      watch.disconnect();
      clearTimeout(giveUp);
    };
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
  // WEB-QA-14OCT-1: a sample-company world only the Park pages know has no run to draw here; its stage and lens
  // addresses go to its Park page (lens links shown disabled with their reason), never a 404 in this shell.
  const parkOnlyWorld = unknownWorld && pathWorld !== null && isParkOnlyWorld(pathWorld);
  useEffect(() => {
    if (!parkOnlyWorld || pathWorld === null) return;
    window.history.replaceState({}, "", `/world/${encodeURIComponent(pathWorld)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [parkOnlyWorld, pathWorld]);
  const screen = unknownWorld ? NOT_FOUND : matched;
  const worldId = unknownWorld ? null : pathWorld;
  const hudWorld = screen ? null : worldId;
  // The stage draws a ?fixture= replay if one was asked for, else the run of the world in the path
  // (the same layout and events the HUD reads), through any client, the fixture client included
  // (FR-WLD-05); anywhere else it keeps its bare grid.
  const clientWorld = useClientWorld(client, world.active ? null : hudWorld);
  const stageWorld = world.active ? world : clientWorld;
  // FR-WLD-07: the stage is veiled only while the recorded run status is "paused" (HR-1).
  const clientStatus = useRunStatus(client, hudWorld);
  const stagePaused = (world.active ? world.status : clientStatus) === "paused";
  // A ?fixture= replay's panels read what the stage has shown of it (the same run, HR-1).
  const fixtureEvents = world.events;
  const fixtureSeq = world.seq;
  const replayed = useMemo(
    () => (world.active ? fixtureEvents.filter((e) => e.seq <= fixtureSeq) : null),
    [world.active, fixtureEvents, fixtureSeq],
  );
  const runScreen = screen !== null && RUN_SCREENS.has(screen.id);
  const needsYouScreen = screen !== null && NEEDS_YOU_SCREENS.has(screen.id);
  const railWorld = worldId ?? (runScreen && !needsYouScreen ? runWorld : null);
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
  if (parkOnlyWorld) return null; // the effect above is moving to the Park page
  return (
    <div
      className="app-shell"
      data-stage-mode={stageMode ? "on" : "off"}
      data-stage-layout={stageLayout ? "1920x1080" : "off"}
      data-strip={world.active || fixtureClient ? "on" : "off"}
      data-replay-badge={speedBadge ? "on" : "off"}
      data-replay-dock={dock ? "on" : "off"}
    >
      {!stageLayout && <TopBar fixture={world.active} />}
      {!mobile && !stageLayout && <PrimaryNav id="left-rail" mobile={false} />}
      {!screen && hudWorld && !mobile && !stageMode && (
        <LevelsPanel
          key={`levels:${hudWorld}`}
          worldId={hudWorld}
          replayed={world.worldId === hudWorld ? replayed : null}
        />
      )}
      {screen ? (
        <ScreenPage key={screen.id} screenId={screen.id}>
          <screen.Component
            key={`${screen.id}:${screen.params.join("/")}`}
            params={screen.params}
          />
        </ScreenPage>
      ) : (
        // Keyed by world: Stage hands its content seam over once, when Pixi is ready.
        <Stage
          key={world.active ? "fixture" : (hudWorld ?? "none")}
          {...(stageWorld.active
            ? {
                onWorld: stageWorld.onWorld,
                seq: stageWorld.seq,
                selected: stageWorld.selected,
                layout: stageWorld.layout,
                worldId: stageWorld.worldId,
              }
            : {})}
          paused={stagePaused}
        />
      )}
      {!screen && !world.active && !stageLayout && <FlowShell />}
      {(world.active || fixtureClient) && (
        // HR-4/BQ-07: permanent (fixture mode, and whenever the fixture client is active), never
        // dismissable, exposed to assistive tech. It sits in a reserved strip along the top edge
        // (Bundle C2): the shell starts below the strip, so it never covers a control, and the
        // strip is fixed so no layout (mobile bottom tabs, stage-mode scale) can push it off-screen.
        <div className="status-strip">
          {/* biome-ignore lint/a11y/useSemanticElements: <output> is for a form/calculation result; this is a persistent mode banner, so an explicit role="status" region fits better. */}
          <div className="fixture-replay-banner" data-testid="fixture-replay-banner" role="status">
            Fixture replay — dev data, not a real run
          </div>
          {speedBadge && (
            // biome-ignore lint/a11y/useSemanticElements: same persistent status region as the banner above, not a form result.
            <div className="speed-badge" data-testid="speed-badge" role="status">
              {speedBadge}
            </div>
          )}
        </div>
      )}
      {clientWorld.note && (
        // Fixed like the fixture alerts, so it never shifts the layout. Says what is true: the world
        // is not drawn until the run has built one.
        <div
          className="live-world-note"
          data-testid="live-world-note"
          role={clientWorld.retry ? "alert" : "status"}
        >
          <p>{clientWorld.note}</p>
          {clientWorld.retry && (
            <button type="button" className="secondary" onClick={clientWorld.retry}>
              Try again
            </button>
          )}
        </div>
      )}
      {world.loadError && (
        <div className="fixture-load-alert" role="alert">
          {world.loadError}
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
              <summary>
                World status
                <HudGlance
                  worldId={hudWorld}
                  replayed={world.worldId === hudWorld ? replayed : null}
                />
              </summary>
              <WorldPanels
                key={hudWorld}
                worldId={hudWorld}
                replayed={world.worldId === hudWorld ? replayed : null}
              />
            </details>
          )}
          <PrimaryNav id="bottom-tabs" mobile />
        </>
      ) : (
        <aside className="right-rail" data-testid="right-rail">
          {dock}
          {railWorld ? (
            <WorldPanels
              key={railWorld}
              worldId={railWorld}
              tabs={hudWorld !== null}
              replayed={world.worldId === railWorld ? replayed : null}
            />
          ) : (
            <>
              {world.active && <ReplayPauseSlot status={world.status} />}
              {/* One rail contract on every route (Bundle C3): card, Needs you, Team. With no run
                  the card is the same box with an honest empty line. */}
              <section className="hud-card" aria-label="Live meter">
                <p data-testid="right-rail-meter">Nothing yet. This fills in once a run starts.</p>
              </section>
              {needsYouScreen ? (
                <NeedsYouRail />
              ) : (
                <>
                  <h2>Needs you</h2>
                  <p>Nothing needs you.</p>
                </>
              )}
              <h2>Team</h2>
              <p>No agents assigned.</p>
            </>
          )}
          {world.active && (
            <>
              <h2>Trace</h2>
              {/* biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1, axe scrollable-region-focusable). */}
              <ul className="trace-list" data-testid="trace-list" aria-label="Trace" tabIndex={0}>
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
      <StagePresenter
        worldId={world.active ? world.worldId : railWorld}
        {...(world.active ? { fixtureEvents: world.events, fixtureFinished: world.finished } : {})}
      />
      <AssistantPanel />
    </div>
  );
}
