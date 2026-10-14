import { useEffect, useRef } from "react";
import { useIsFixtureClient, useReplaySpeed } from "./api/ClientProvider";
import { AssistantPanel } from "./assistant/AssistantPanel";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { usePathname } from "./router";
import { FlowShell } from "./screens/FlowShell";
import { NotFound } from "./screens/NotFound";
import { PrimaryNav } from "./screens/PrimaryNav";
import { ScreenPage } from "./screens/ScreenPage";
import { TopBar } from "./screens/TopBar";
import { type ScreenMatch, matchScreen } from "./screens/routes";
import { speedBadgeText } from "./world/speed";

/** Screens that read the replayed run from a bare address (AGW-08 group B): HR-6 applies, so a replay that is not at
 * its recorded pace says so. */
const RUN_SCREENS: ReadonlySet<string> = new Set([
  "S-15",
  "S-16",
  "S-17",
  "S-18",
  "S-19",
  "S-23",
]);
const NOT_FOUND: ScreenMatch = { id: "not-found", params: [], Component: NotFound };

/** The addresses the old app still owns until its last screens move into the Park pages (OLD-UI-OUT): the intake
 * flow and the screens of waves 3 and 4. A world's stage, lenses and the Needs-you page are Park pages now
 * (worldView/), so this frame draws no stage and no right rail. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  const fixtureClient = useIsFixtureClient();
  const replaySpeed = useReplaySpeed();
  const path = usePathname();
  const matched = matchScreen(path); // null: the flow shell
  const previousPath = useRef(path);
  // After a route change a full-page screen's heading takes focus, so keyboard and screen-reader users keep their
  // place (the flow shell does the same for its own heading).
  useEffect(() => {
    if (previousPath.current === path) return; // not the first render, nor StrictMode's second effect
    previousPath.current = path;
    const focusHeading = (): boolean => {
      const h1 = document.querySelector<HTMLElement>(".screen-page h1, .flow-heading");
      if (!h1 || h1.getClientRects().length === 0) return false; // not there yet, or hidden
      h1.setAttribute("tabindex", "-1");
      h1.focus();
      return true;
    };
    if (focusHeading()) return;
    // A screen is a code-split chunk (NFR-01): its heading arrives with it. Focus it then, unless the person has
    // moved focus somewhere else in the meantime (it is still where the navigation left it).
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
  // A path under /world/ that no screen owns is "Not found" (the Park pages answer for the ones they own).
  const screen = matched ?? (/^\/world\//.test(path) ? NOT_FOUND : null);
  // HR-6: a replay that is not at its recorded pace always says so, in words, in a status region.
  const speedBadge =
    fixtureClient && screen !== null && RUN_SCREENS.has(screen.id)
      ? speedBadgeText(replaySpeed)
      : null;
  return (
    <div
      className="app-shell"
      data-stage-mode="off"
      data-stage-layout="off"
      data-strip={fixtureClient ? "on" : "off"}
      data-replay-badge={speedBadge ? "on" : "off"}
    >
      <TopBar fixture={false} />
      {!mobile && <PrimaryNav id="left-rail" mobile={false} />}
      {screen ? (
        <ScreenPage key={screen.id} screenId={screen.id}>
          <screen.Component
            key={`${screen.id}:${screen.params.join("/")}`}
            params={screen.params}
          />
        </ScreenPage>
      ) : (
        <FlowShell />
      )}
      {fixtureClient && (
        // HR-4/BQ-07: permanent (whenever the fixture client is active), never dismissable, exposed to assistive
        // tech. It sits in a reserved strip along the top edge: the shell starts below the strip, so it never
        // covers a control.
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
      {mobile && <PrimaryNav id="bottom-tabs" mobile />}
      <AssistantPanel />
    </div>
  );
}
