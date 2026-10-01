import { useCallback, useEffect, useState } from "react";

export type FlowScreen = "Start" | "Understanding" | "Approaches" | "World" | "Delivery";

export interface FlowRoute {
  readonly screen: FlowScreen;
  readonly taskId?: string;
  readonly worldId?: string;
}

const UNDERSTANDING_RE = /^\/task\/([^/]+)\/understanding\/?$/;
const APPROACHES_RE = /^\/task\/([^/]+)\/approaches\/?$/;
const DELIVERY_RE = /^\/world\/([^/]+)\/delivery\/?$/;
const WORLD_RE = /^\/world\/([^/]+)\/?$/;

export function matchFlowRoute(pathname: string): FlowRoute {
  const uMatch = UNDERSTANDING_RE.exec(pathname);
  if (uMatch?.[1]) {
    return { screen: "Understanding", taskId: decodeURIComponent(uMatch[1]) };
  }
  const aMatch = APPROACHES_RE.exec(pathname);
  if (aMatch?.[1]) {
    return { screen: "Approaches", taskId: decodeURIComponent(aMatch[1]) };
  }
  const dMatch = DELIVERY_RE.exec(pathname);
  if (dMatch?.[1]) {
    return { screen: "Delivery", worldId: decodeURIComponent(dMatch[1]) };
  }
  const wMatch = WORLD_RE.exec(pathname);
  if (wMatch?.[1]) {
    return { screen: "World", worldId: decodeURIComponent(wMatch[1]) };
  }
  return { screen: "Start" };
}

export function navigateFlow(to: string): void {
  if (typeof window === "undefined") return;
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useFlowRoute(): {
  readonly route: FlowRoute;
  readonly navigate: (to: string) => void;
} {
  const [route, setRoute] = useState<FlowRoute>(() =>
    matchFlowRoute(typeof window !== "undefined" ? window.location.pathname : "/"),
  );

  useEffect(() => {
    const onPopState = () => setRoute(matchFlowRoute(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((to: string) => {
    navigateFlow(to);
  }, []);

  return { route, navigate };
}
