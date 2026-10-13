// UI-10 W20: compose the recorded stage and Park shell at their shared mount boundary.
// The stream, renderer and scrubber stay the existing FR-WLD-04/08 implementation.
import { useEffect, useMemo, useState } from "react";
import { createFixtureApi } from "./park/api/fixtureApi";
import { ParkProvider, useApp, useSessionAuth } from "./park/app/context";
import { AppShell } from "./park/shell/AppShell";
import { ParkAuthProvider } from "./park/shell/auth";
import { themeFor } from "./park/tokens/themes";
import "./park/tokens/park.css";
import "./park/tokens/themes.css";
import { ReplayPauseSlot } from "./screens/PauseSlot";
import { ReplayScrubber } from "./screens/ReplayScrubber";
import { StagePresenter } from "./screens/StagePresenter";
import { WorldPanels } from "./screens/WorldPanels";
import { Stage } from "./stage/Stage";
import { useWorldFixture } from "./world/useWorldFixture";
import "./recorded-replay.css";

function Replay() {
  const app = useApp();
  const world = useWorldFixture();
  useEffect(() => {
    const before = document.title;
    document.title = "Sample recording · Tilo";
    return () => {
      document.title = before;
    };
  }, []);
  const replayed = useMemo(
    () => world.events.filter((e) => e.seq <= world.seq),
    [world.events, world.seq],
  );
  return (
    <div
      data-park
      data-time={app.time}
      data-motion={app.motion}
      data-theme={themeFor(app.prefs.theme)}
    >
      <AppShell>
        <section className="recorded-replay" data-testid="recorded-replay">
          <h1>Sample recording</h1>
          {/* biome-ignore lint/a11y/useSemanticElements: persistent replay status, not a calculation */}
          <p role="status">This is a recorded sample, not your task. No work is being sent.</p>
          {/* biome-ignore lint/a11y/useSemanticElements: persistent replay speed status */}
          {world.speedLabel && <p role="status">{world.speedLabel}</p>}
          {world.loadError && <p role="alert">{world.loadError}</p>}
          <div className="recorded-replay__player">
            <Stage
              onWorld={world.onWorld}
              seq={world.seq}
              selected={world.selected}
              layout={world.layout}
              worldId={world.worldId}
              paused={world.status === "paused"}
            />
            <aside className="recorded-replay__rail" aria-label="Recorded run">
              <ReplayScrubber
                worldId={world.worldId}
                events={world.events}
                finished={world.finished}
                fixture
              />
              <ReplayPauseSlot status={world.status} />
              {world.worldId && <WorldPanels worldId={world.worldId} replayed={replayed} />}
              <h2>Trace</h2>
              <ul data-testid="trace-list">
                {world.trace.slice(-250).map((row) => (
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
            </aside>
          </div>
          <StagePresenter
            worldId={world.worldId}
            fixtureEvents={world.events}
            fixtureFinished={world.finished}
          />
        </section>
      </AppShell>
    </div>
  );
}

export default function RecordedReplay() {
  const auth = useSessionAuth();
  const [api] = useState(createFixtureApi);
  return (
    <ParkProvider api={api} demo worldClient={null}>
      <ParkAuthProvider auth={auth}>
        <Replay />
      </ParkAuthProvider>
    </ParkProvider>
  );
}
