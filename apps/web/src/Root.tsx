// The mount point: the Park app serves the root paths (/, /worlds, /world/:id, /team, ...) and the /park
// alias; the old app serves every other address (the stage at /world/:id/stage and the kept screens). The
// Park app is a dynamic import, so a visit to a kept screen never loads it (NFR-01). `isParkPath` is the one
// shared predicate for the split (WEB-CUTOVER).
import { Suspense, lazy } from "react";
import { App } from "./App";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

const ParkApp = lazy(() => import("./park/app/ParkApp"));

export function Root() {
  const pathname = usePathname();
  if (!isParkPath(pathname)) return <App />;
  return (
    <Suspense fallback={null}>
      <ParkApp />
    </Suspense>
  );
}
