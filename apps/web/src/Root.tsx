// The mount point: the Park app serves the root paths (/, /worlds, /world/:id, /team, ...), the /park alias
// and every address no screen owns (its own "Page not found"); the old app serves exactly the addresses it
// keeps (`isKeptPath`: /start, the stage at /world/:id/stage and the other kept screens). Both apps are
// dynamic imports, so a visit to a kept screen never loads the Park app (NFR-01). `isParkPath` and
// `isKeptPath` are the shared predicates for the split (WEB-CUTOVER). /privacy and /terms (WEB-LEGAL) are
// static public pages: their own chunk, loading neither app (no sign-in, no API). SEC-15: both apps sit behind the
// sign-in gate; with no Firebase here (a local host, a build with no config) the gate shows the app at once.
import { type ReactNode, Suspense, lazy, useEffect, useMemo, useSyncExternalStore } from "react";
import { AccessLayer, needsAccess } from "./access/AccessLayer";
import { API_URL, appCheckToken, authToken } from "./api/ClientProvider";
import { HttpClient } from "./api/http";
import { SignInGate } from "./auth/SignInGate";
import { session } from "./auth/session";
import { isKeptPath } from "./keptPaths";
import { legalKind } from "./legal/legalPaths";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

// Both apps are chunks: the landing (Park Home) never ships the old app's shell, and a kept screen never
// loads the Park app (NFR-01).
const App = lazy(() => import("./App").then((m) => ({ default: m.App })));
const ParkApp = lazy(() => import("./park/app/ParkApp"));
const LegalPage = lazy(() => import("./legal/LegalPage"));

/** SEC-15 W0b: on a deployment with an API, a Google sign-in is asked who it is before the app (the server enforces it).
 * A demo session reads the sample company and is not asked; a local host or a build with no API has no gate. */
function AccessGuard({ children }: { children: ReactNode }) {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  const base = API_URL?.trim();
  const http = useMemo(
    () => (base ? new HttpClient({ baseUrl: base, appCheckToken, authToken }) : null),
    [base],
  );
  if (!http || !needsAccess(state.status, base)) return <>{children}</>;
  return (
    // keyed on who is signed in: another account on the same page never inherits the first one's verdict
    <AccessLayer
      key={state.status === "google" ? (state.email ?? state.displayName ?? "google") : "google"}
      http={http}
    >
      {children}
    </AccessLayer>
  );
}

export function Root() {
  const pathname = usePathname();
  const legal = legalKind(pathname);
  const park = isParkPath(pathname) || !isKeptPath(pathname);
  // ONBOARD-1: the first-run welcome and tour register themselves with the Park shell (park/shell/tour.ts): a chunk of
  // its own, started beside the Park app's and never awaited by it. The kept screens and legal pages never load it.
  useEffect(() => {
    if (park && !legal) void import("./onboarding/register");
  }, [park, legal]);
  if (legal) {
    return (
      <Suspense fallback={null}>
        <LegalPage kind={legal} />
      </Suspense>
    );
  }
  return (
    <SignInGate auth={session}>
      <AccessGuard>
        <Suspense fallback={null}>{park ? <ParkApp /> : <App />}</Suspense>
      </AccessGuard>
    </SignInGate>
  );
}
