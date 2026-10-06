// The mount point: the existing app everywhere except under /park, where the Park app takes over. The
// Park app is a dynamic import, so a landing visit never loads it (NFR-01). The old app is untouched
// until the cutover PR.
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
