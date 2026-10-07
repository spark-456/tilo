// The mount point: the Park app serves the root paths (/, /worlds, /world/:id, /team, ...), the /park alias
// and every address no screen owns (its own "Page not found"); the old app serves exactly the addresses it
// keeps (`isKeptPath`: /start, the stage at /world/:id/stage and the other kept screens). Both apps are
// dynamic imports, so a visit to a kept screen never loads the Park app (NFR-01). `isParkPath` and
// `isKeptPath` are the shared predicates for the split (WEB-CUTOVER). /privacy and /terms (WEB-LEGAL) are
// static public pages: their own chunk, loading neither app (no sign-in, no API).
import { Suspense, lazy } from "react";
import { isKeptPath } from "./keptPaths";
import { legalKind } from "./legal/legalPaths";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

// Both apps are chunks: the landing (Park Home) never ships the old app's shell, and a kept screen never
// loads the Park app (NFR-01).
const App = lazy(() => import("./App").then((m) => ({ default: m.App })));
const ParkApp = lazy(() => import("./park/app/ParkApp"));
const LegalPage = lazy(() => import("./legal/LegalPage"));

export function Root() {
  const pathname = usePathname();
  const legal = legalKind(pathname);
  if (legal) {
    return (
      <Suspense fallback={null}>
        <LegalPage kind={legal} />
      </Suspense>
    );
  }
  const park = isParkPath(pathname) || !isKeptPath(pathname);
  return <Suspense fallback={null}>{park ? <ParkApp /> : <App />}</Suspense>;
}
