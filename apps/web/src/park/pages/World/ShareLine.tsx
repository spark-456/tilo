// BQ-CTX-TEAMWORLD (ADR-0040 decision 9, FR-TEAM-02; HR-1): the world's sharing line. It says what the world's own
// recorded `world.share_changed` events say, the latest per team, and nothing else: no recorded event, or a feed
// that cannot be read, shows nothing at all (not an error, not a guess). It is plain text and never moves.
import { type FeedClient, readShareLine } from "../../api/live/shareLine";
import { useRead } from "./TeamShare";
import "./ShareLine.css";

export function ShareLine({ client, worldId }: { client: FeedClient; worldId: string }) {
  const [view] = useRead(() => readShareLine(client, worldId), [client, worldId]);
  if (view.status !== "ready" || view.value === null) return null;
  const { on, off } = view.value;
  if (on.length === 0 && off.length === 0) return null;
  const words =
    on.length > 0
      ? `Shared with team ${on.join(", ")}.${off.length > 0 ? ` Turned off for ${off.join(", ")}.` : ""}`
      : "Team sharing is off.";
  return (
    <p className="park-world-sharebadge" data-testid="park-world-share-line">
      <span>{words}</span>
      <span className="park-world-sharenote">As recorded in this world’s events.</span>
    </p>
  );
}
