// The mount point: the Park app serves the root paths (/, /worlds, /world/:id, /team, ...), the /park alias
// and every address no screen owns (its own "Page not found"); the old app serves exactly the addresses it
// keeps (`isKeptPath`: /start, the stage at /world/:id/stage and the other kept screens). Both apps are
// dynamic imports, so a visit to a kept screen never loads the Park app (NFR-01). `isParkPath` and
// `isKeptPath` are the shared predicates for the split (WEB-CUTOVER). SEC-15: both sit behind the sign-in gate;
// with no Firebase here (a local host, a build with no config) the gate shows the app at once and no sign-in UI.
import { Suspense, lazy } from "react";
import { SignInGate } from "./auth/SignInGate";
import { session } from "./auth/session";
import { isKeptPath } from "./keptPaths";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

// Both apps are chunks: the landing (Park Home) never ships the old app's shell, and a kept screen never
// loads the Park app (NFR-01).
const App = lazy(() => import("./App").then((m) => ({ default: m.App })));
const ParkApp = lazy(() => import("./park/app/ParkApp"));

export function Root() {
  const pathname = usePathname();
  const park = isParkPath(pathname) || !isKeptPath(pathname);
  return (
    <SignInGate auth={session}>
      <Suspense fallback={null}>{park ? <ParkApp /> : <App />}</Suspense>
    </SignInGate>
  );
}
