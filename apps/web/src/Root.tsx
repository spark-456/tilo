// The mount point: the Park app serves the root paths (/, /worlds, /world/:id, /team, ...), the /park alias
// and every address no screen owns (its own "Page not found"); the old app serves exactly the addresses it
// keeps (`isKeptPath`: /start, the stage at /world/:id/stage and the other kept screens). Both apps are
// dynamic imports, so a visit to a kept screen never loads the Park app (NFR-01). `isParkPath` and
// `isKeptPath` are the shared predicates for the split (WEB-CUTOVER).
import { Suspense, lazy } from "react";
import { isKeptPath } from "./keptPaths";
import { isHomeAddress, isParkPath } from "./park/app/router";
import { usePathname } from "./router";
import "./park/tokens/park.css";
import "./rootFrame.css";

// Both apps are chunks: the landing (Park Home) never ships the old app's shell, and a kept screen never
// loads the Park app (NFR-01).
const App = lazy(() => import("./App").then((m) => ({ default: m.App })));
const ParkApp = lazy(() => import("./park/app/ParkApp"));

// The landing visit is the Home page: its page chunk is requested now, beside the Park app chunk, not after that
// chunk has arrived and run (a whole round trip later on a phone, NFR-01). `lazy()` in the page registry reuses
// the same module, so nothing loads twice. Any other address never asks for it.
if (isHomeAddress()) void import("./park/pages/Home/HomePage");

// While a chunk is on its way the page is a plain frame in the colour the real page starts with (the Park boot
// splash's paper; the old app's surface), not a blank page: no text, no motion, fixed to the viewport, so the page
// arriving moves nothing (NFR-01, CLS 0). The Park frame carries `data-park` only to read the Park tokens.
function RootFrame({ park }: { park: boolean }) {
  return (
    <div
      className="root-frame"
      data-testid="root-frame"
      data-app={park ? "park" : "kept"}
      {...(park ? { "data-park": "" } : {})}
      aria-hidden="true"
    />
  );
}

export function Root() {
  const pathname = usePathname();
  const park = isParkPath(pathname) || !isKeptPath(pathname);
  return <Suspense fallback={<RootFrame park={park} />}>{park ? <ParkApp /> : <App />}</Suspense>;
}
