// THROWAWAY (WEB-3b validation only)
import { Suspense, lazy } from "react";
import { App } from "./App";
import { isParkPath } from "./park/app/router";
import { usePathname } from "./router";

const ParkApp = lazy(() => import("./park/app/ParkApp"));

export function Root() {
  const path = usePathname();
  if (!isParkPath(path)) return <App />;
  return (
    <Suspense fallback={null}>
      <ParkApp />
    </Suspense>
  );
}
