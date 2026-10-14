// The World lens (PRD 18.3 S-04): the live isometric stage inside the Park shell, with the replay dock and the side
// panels. The stage draws a ?fixture= replay if one was asked for, else the run of the world in the path (the same
// layout and events the panels read), through any client, the fixture client included (FR-WLD-05).
import { useMemo } from "react";
import { useClient, useIsFixtureClient, useReplaySpeed } from "../api/ClientProvider";
import { useStageMode } from "../display/stageMode";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { Stage } from "../stage/Stage";
import { useRunStatus } from "../world/runLog";
import { speedBadgeText } from "../world/speed";
import { useClientWorld } from "../world/useClientWorld";
import type { WorldFixtureState } from "../world/useWorldFixture";
import { LensFrame } from "./LensFrame";
import { LoggedDock, ReplayDock } from "./ReplayDock";
import { StagePresenter } from "./StagePresenter";
import { HudGlance, StageRail } from "./StageRail";

/** Memoised rows: each applied event adds one row instead of re-rendering the whole list. The trace list is the
 * ?fixture= replay's own (App's right rail used to hold it). */
const TRACE_ROWS = 250;

export function StageView({
  worldId,
  fixture,
}: {
  worldId: string;
  /** The ?fixture= replay state, or an inactive one. */
  fixture: WorldFixtureState;
}) {
  const client = useClient();
  const fixtureClient = useIsFixtureClient();
  const replaySpeed = useReplaySpeed();
  const mobile = useMediaQuery("(max-width: 767px)");
  const wideStage = useMediaQuery("(min-width: 1920px)");
  // Stage mode is a display setting (PRD 9.6, FR-WLD-12): it hides the lens chrome, never the stage or its facts.
  const [stageMode] = useStageMode();
  const stageLayout = stageMode && (wideStage || window.innerWidth >= 1920);
  const clientWorld = useClientWorld(client, fixture.active ? null : worldId);
  const stageWorld = fixture.active ? fixture : clientWorld;
  // FR-WLD-07: the stage is veiled only while the recorded run status is "paused" (HR-1).
  const clientStatus = useRunStatus(client, worldId);
  const paused = (fixture.active ? fixture.status : clientStatus) === "paused";
  const fixtureEvents = fixture.events;
  const fixtureSeq = fixture.seq;
  // A ?fixture= replay's panels read what the stage has shown of it (the same run, HR-1).
  const replayed = useMemo(
    () => (fixture.active ? fixtureEvents.filter((e) => e.seq <= fixtureSeq) : null),
    [fixture.active, fixtureEvents, fixtureSeq],
  );
  // HR-6: a replay that is not at its recorded pace always says so, in words, in a status region.
  const speedBadge = fixture.active ? fixture.speedLabel : speedBadgeText(replaySpeed);
  const railWorld = fixture.active ? fixture.worldId : worldId;
  const dock = fixture.active ? (
    <ReplayDock
      worldId={fixture.worldId}
      events={fixture.events}
      finished={fixture.finished}
      fixture
    />
  ) : (
    <LoggedDock worldId={worldId} fixture={fixtureClient} />
  );
  return (
    <LensFrame
      worldId={fixture.active ? fixture.worldId : worldId}
      current="stage"
      title="World"
      hideTabs={stageMode}
    >
      <div
        className="park-view-stagegrid"
        data-testid="world-stage-view"
        data-stage-mode={stageMode ? "on" : "off"}
        data-stage-layout={stageLayout ? "1920x1080" : "off"}
      >
        <div className="park-view-stagecol">
          {fixture.active || fixtureClient ? (
            // HR-4: a recorded replay says so, always, in words; never dismissable.
            // biome-ignore lint/a11y/useSemanticElements: a persistent mode banner, not a form result.
            <div className="park-view-banner" data-testid="fixture-replay-banner" role="status">
              Recorded replay: sample data, not a live run
            </div>
          ) : null}
          {speedBadge ? (
            // biome-ignore lint/a11y/useSemanticElements: the same persistent status region as the banner.
            <div className="park-view-banner" data-testid="speed-badge" role="status">
              {speedBadge}
            </div>
          ) : null}
          <div className="park-view-stagebox">
            <Stage
              key={fixture.active ? "fixture" : worldId}
              landmark={false}
              {...(stageWorld.active
                ? {
                    onWorld: stageWorld.onWorld,
                    seq: stageWorld.seq,
                    selected: stageWorld.selected,
                    layout: stageWorld.layout,
                    worldId: stageWorld.worldId,
                  }
                : {})}
              paused={paused}
            />
          </div>
          {clientWorld.note ? (
            // Says what is true: the world is not drawn until the run has built one.
            <div
              className="park-view-alert"
              data-testid="live-world-note"
              role={clientWorld.retry ? "alert" : "status"}
            >
              <p>{clientWorld.note}</p>
              {clientWorld.retry ? (
                <button type="button" className="park-view-chiplink" onClick={clientWorld.retry}>
                  Try again
                </button>
              ) : null}
            </div>
          ) : null}
          {fixture.loadError ? (
            <div className="park-view-alert" role="alert">
              {fixture.loadError}
            </div>
          ) : null}
          {mobile ? dock : null}
        </div>
        {mobile ? (
          <details
            className="park-view-sheet-hud"
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              // Closing the sheet hides the focused control, so focus goes back to its summary.
              e.currentTarget.open = false;
              e.currentTarget.querySelector("summary")?.focus();
            }}
          >
            <summary>
              World status <HudGlance worldId={railWorld} replayed={replayed} />
            </summary>
            <StageRail
              key={railWorld}
              worldId={railWorld}
              replayed={replayed}
              pauseStatus={fixture.active ? fixture.status : null}
            />
          </details>
        ) : (
          <aside className="park-view-side" data-testid="right-rail">
            {dock}
            <StageRail
              key={railWorld}
              worldId={railWorld}
              replayed={replayed}
              pauseStatus={fixture.active ? fixture.status : null}
            />
            {fixture.active ? (
              <section className="park-view-card" aria-label="Trace">
                <h2 className="park-view-h2">Trace</h2>
                <ul
                  className="park-view-tracelist"
                  data-testid="trace-list"
                  aria-label="Trace"
                  // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1).
                  tabIndex={0}
                >
                  {fixture.trace.length > TRACE_ROWS ? (
                    <li>
                      Showing the latest {TRACE_ROWS} of {fixture.trace.length} events.
                    </li>
                  ) : null}
                  {fixture.trace.slice(-TRACE_ROWS).map((row) => (
                    <li
                      key={row.seq}
                      data-testid="trace-row"
                      data-seq={row.seq}
                      data-event-type={row.type}
                    >
                      {row.seq} {row.type}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </aside>
        )}
      </div>
      <StagePresenter
        worldId={railWorld}
        {...(fixture.active
          ? { fixtureEvents: fixture.events, fixtureFinished: fixture.finished }
          : {})}
      />
    </LensFrame>
  );
}
