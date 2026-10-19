// OLD-UI-OUT-2: what the Park shell shows at a world's lens addresses and at /needs-you. Root.tsx hands it the parsed
// route; the shell around it (navigation, the one <main>, title, heading focus) is ParkApp's. Its own chunk, so the
// Park landing never carries the stage or the lenses (NFR-01).
import { useEffect } from "react";
import { useWorldKnown } from "../api/ClientProvider";
import { isParkOnlyWorld } from "../parkWorlds";
import { useWorldFixture } from "../world/useWorldFixture";
import { DeliveryView } from "./DeliveryView";
import { InspectView } from "./InspectView";
import { NeedsYouView } from "./NeedsYouView";
import { NotFoundView } from "./NotFoundView";
import { StageView } from "./StageView";
import { StoryView } from "./StoryView";
import { TraceView } from "./TraceView";
import type { ViewRoute } from "./routes";
import { overviewPath } from "./routes";
import "./WorldView.css";

function WorldLens({ route }: { route: Exclude<ViewRoute, { kind: "needs" }> }) {
  const { worldId } = route;
  const fixture = useWorldFixture();
  const known = useWorldKnown(worldId);
  // A world id the client does not know is "Page not found", never another world's run in its place.
  const unknown = !known && !fixture.active;
  // WEB-QA-14OCT-1: a sample-company world only the Park pages know has no run to draw here; its stage and lens
  // addresses go to its Park page, never a 404.
  const parkOnly = unknown && isParkOnlyWorld(worldId);
  useEffect(() => {
    if (!parkOnly) return;
    window.history.replaceState({}, "", overviewPath(worldId));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [parkOnly, worldId]);
  if (parkOnly) return null; // the effect above is moving to the Park page
  if (unknown) return <NotFoundView />;
  if (route.kind === "inspect") return <InspectView worldId={worldId} itemId={route.itemId} />;
  switch (route.lens) {
    case "story":
      return <StoryView worldId={worldId} />;
    case "trace":
      return <TraceView worldId={worldId} />;
    case "delivery":
      return <DeliveryView worldId={worldId} />;
    default:
      return <StageView worldId={worldId} fixture={fixture} />;
  }
}

export default function WorldViewApp({ route }: { route: ViewRoute }) {
  if (route.kind === "needs") return <NeedsYouView sheet={route.sheet} />;
  return <WorldLens route={route} />;
}
