// PRD 18.3 flow routes on the History API, no dependency: /task/:id/understanding S-02,
// /task/:id/approaches S-03, /world/:id/stage S-04 (WEB-CUTOVER: `/` and `/world/:id` are Park pages now,
// so S-01's body is only the intake form at /start). Start is also this table's fallback, but Root.tsx only
// hands the old app the addresses `isKeptPath` lists, so an unknown address never reaches it (it is the Park
// "Page not found"); routes.tsx owns every other screen (S-12 /world/:id/delivery included) and "Not found"
// under /world/ and /task/.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export type FlowScreen = "Start" | "Understanding" | "Approaches" | "World";

export type FlowRoute =
  | { readonly screen: "Start" }
  | { readonly screen: "Understanding" | "Approaches"; readonly taskId: string }
  | { readonly screen: "World"; readonly worldId: string };

const ROUTES = [
  { re: /^\/task\/([^/]+)\/understanding\/?$/, screen: "Understanding", key: "taskId" },
  { re: /^\/task\/([^/]+)\/approaches\/?$/, screen: "Approaches", key: "taskId" },
  { re: /^\/world\/([^/]+)\/stage\/?$/, screen: "World", key: "worldId" },
] as const;

/** The live stage (S-04) of a world. `/world/:id` is the Park World overview, so the stage has its own address. */
export const stagePath = (worldId: string): string => `/world/${encodeURIComponent(worldId)}/stage`;

export function matchFlowRoute(pathname: string): FlowRoute {
  for (const { re, screen, key } of ROUTES) {
    const raw = re.exec(pathname)?.[1];
    if (raw === undefined) continue;
    try {
      const id = decodeURIComponent(raw);
      return key === "taskId"
        ? { screen: screen as "Understanding" | "Approaches", taskId: id }
        : { screen: "World", worldId: id };
    } catch {
      return { screen: "Start" }; // a malformed escape such as %E0 is an unknown path, not a crash
    }
  }
  return { screen: "Start" };
}

export function navigateFlow(to: string): void {
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useFlowRoute(): { readonly route: FlowRoute } {
  const [route, setRoute] = useState<FlowRoute>(() => matchFlowRoute(window.location.pathname));
  useEffect(() => {
    const onPopState = () => setRoute(matchFlowRoute(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  return { route };
}

export const useNavigate = () => useCallback(navigateFlow, []);

/** The current path, re-read on every History API navigation. */
export const usePathname = (): string =>
  useSyncExternalStore(
    (onChange) => {
      window.addEventListener("popstate", onChange);
      return () => window.removeEventListener("popstate", onChange);
    },
    () => window.location.pathname,
  );
