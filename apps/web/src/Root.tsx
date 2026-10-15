// The mount point: the Park app serves every address (/, /worlds, /world/:id, /team, ...), the /park alias and every
// address no page owns (its own "Page not found"). The old app is gone (OLD-UI-OUT Final). /privacy and /terms
// (WEB-LEGAL) are static public pages: their own chunk, loading no app (no sign-in, no API). /oauth/google/callback
// (ADR-0035 L4) is its own chunk behind the sign-in gate; it loads no app. SEC-15: the Park app sits behind the
// sign-in gate; with no Firebase here (a local host, a build with no config) the gate shows the app at once.
import { type ReactNode, Suspense, lazy, useEffect, useMemo, useSyncExternalStore } from "react";
import { AccessLayer, needsAccess } from "./access/AccessLayer";
import { API_URL, appCheckToken, authToken } from "./api/ClientProvider";
import { PersonStartup } from "./api/PersonStartup";
import { HttpClient } from "./api/http";
import { SignInGate } from "./auth/SignInGate";
import { session } from "./auth/session";
import { legalKind } from "./legal/legalPaths";
import { takeCallbackParams } from "./oauth/capture";
import { isOAuthCallback } from "./oauth/paths";
import { adminRedirect } from "./park/app/adminRedirect";
import { captureJoinToken } from "./park/pages/Join/joinToken";
import { usePathname } from "./router";
import { type ViewRoute, parseViewPath, viewTitle } from "./worldView/routes";

// The Park app is a chunk of its own, so the legal pages and the OAuth callback load without it (NFR-01).
const ParkApp = lazy(() => import("./park/app/ParkApp"));
const LegalPage = lazy(() => import("./legal/LegalPage"));
const OAuthCallback = lazy(() => import("./oauth/CallbackRoute"));
// OLD-UI-OUT-2: a world's lenses and the Needs-you page are Park pages (the Park shell frames them); their code is a
// chunk of its own that only these addresses load.
const WorldViewApp = lazy(() => import("./worldView/WorldViewApp"));
// The Park component gallery (WEB-2): a dev-build address only; its chunk is never reached from the landing bundle.
const DevComponents = import.meta.env.DEV
  ? lazy(() => import("./park/dev/Components").then((m) => ({ default: m.Components })))
  : null;
const DEV_COMPONENTS = /^\/dev\/components\/?$/;

/** The shell's routed view for a lens, inspect or Needs-you address. */
function routedOf(view: ViewRoute) {
  const key =
    view.kind === "lens"
      ? `${view.worldId}/${view.lens}`
      : view.kind === "inspect"
        ? `${view.worldId}/inspect/${view.itemId}`
        : `needs-you/${view.sheet}`;
  return {
    title: viewTitle(view),
    routeKey: `view:${key}`,
    content: (
      <Suspense fallback={null}>
        <WorldViewApp route={view} />
      </Suspense>
    ),
  };
}

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
      <PersonStartup http={http}>{children}</PersonStartup>
    </AccessLayer>
  );
}

export function Root() {
  captureJoinToken();
  const pathname = usePathname();
  // A bookmark of a retired screen (the old intake flow, mail, the team console) is replaced by its Park home before it renders.
  const redirect = adminRedirect(pathname, window.location.search);
  useEffect(() => {
    if (redirect) {
      window.history.replaceState({}, "", redirect);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }, [redirect]);
  const legal = legalKind(pathname);
  // ADR-0035 LC-02: Google's redirect lands here. The code and state leave the address bar before anything else renders.
  const oauth = isOAuthCallback(pathname) ? takeCallbackParams() : undefined;
  const view = parseViewPath(pathname);
  // ONBOARD-1: the first-run welcome and tour register themselves with the Park shell (park/shell/tour.ts): a chunk of
  // its own, started beside the Park app's and never awaited by it. The legal pages and the OAuth callback never load it.
  useEffect(() => {
    if (!legal && oauth === undefined) void import("./onboarding/register");
  }, [legal, oauth]);
  if (redirect) return null;
  if (oauth !== undefined) {
    return (
      <Suspense fallback={null}>
        <OAuthCallback params={oauth} />
      </Suspense>
    );
  }
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
        <Suspense fallback={null}>
          {DevComponents && DEV_COMPONENTS.test(pathname) ? (
            <DevComponents />
          ) : (
            <ParkApp {...(view ? { routed: routedOf(view) } : {})} />
          )}
        </Suspense>
      </AccessGuard>
    </SignInGate>
  );
}
