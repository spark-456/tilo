// The mount point: the existing app everywhere except under /park, where the Park app takes over. The
// Park app is a dynamic import, so a landing visit never loads it (NFR-01). The old app is untouched
// until the cutover PR.
import { Suspense, lazy } from "react";
import { App } from "./App";
import { SignInGate } from "./auth/SignInGate";
import { session } from "./auth/session";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

const ParkApp = lazy(() => import("./park/app/ParkApp"));

export function Root() {
  const pathname = usePathname();
  // SEC-15: the whole app sits behind sign-in; no Firebase here (a local host, no config) means no gate at all.
  return (
    <SignInGate auth={session}>
      {!isParkPath(pathname) ? (
        <App />
      ) : (
        <Suspense fallback={null}>
          <ParkApp />
        </Suspense>
      )}
    </SignInGate>
  );
}
