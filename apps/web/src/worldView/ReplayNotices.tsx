// HR-4 and HR-6: a recorded replay says so, always, in words, and never dismissably; a replay that is not at its
// recorded pace says that too. Shared by the stage and the Needs-you pages, which both read the replayed run.
import { useIsFixtureClient, useReplaySpeed } from "../api/ClientProvider";
import { speedBadgeText } from "../world/speed";

export function ReplayNotices({
  active,
  speedLabel,
}: {
  /** True when the run on screen is a recorded replay (the fixture client, or a ?fixture= replay). */
  active?: boolean;
  /** The ?fixture= replay's own speed label; the fixture client's speed is read from the client. */
  speedLabel?: string | null;
}) {
  const fixtureClient = useIsFixtureClient();
  const replaySpeed = useReplaySpeed();
  const replay = active === true || fixtureClient;
  const badge = speedLabel !== undefined ? speedLabel : speedBadgeText(replaySpeed);
  return (
    <>
      {replay ? (
        // biome-ignore lint/a11y/useSemanticElements: a persistent mode banner, not a form result.
        <div className="park-view-banner" data-testid="fixture-replay-banner" role="status">
          Recorded replay: sample data, not a live run
        </div>
      ) : null}
      {badge ? (
        // biome-ignore lint/a11y/useSemanticElements: the same persistent status region as the banner.
        <div className="park-view-banner" data-testid="speed-badge" role="status">
          {badge}
        </div>
      ) : null}
    </>
  );
}
