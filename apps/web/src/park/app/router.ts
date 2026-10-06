// The /park/<page> router (README "Routes"; plan section 1): pure path functions plus one hook. This is
// the only file under park/ that reads the address bar; pages get `app.page` and `app.params`.
import { useMemo, useSyncExternalStore } from "react";
import { PAGE_IDS, type PageId, type Params } from "./AppCtx";

export interface ParkRoute {
  page: PageId;
  params: Params;
}

// The query names each page keeps (README "Routes"); anything else is dropped. The world id is a path
// segment, not a query value.
const QUERY: Partial<Record<PageId, string>> = { skills: "id", team: "focus", profile: "tab" };

const isPageId = (s: string | undefined): s is PageId => PAGE_IDS.some((p) => p === s);

export function isParkPath(pathname: string): boolean {
  return pathname === "/park" || pathname.startsWith("/park/");
}

function decodeSegment(raw: string): string | null {
  try {
    return decodeURIComponent(raw);
  } catch {
    return null; // a malformed escape such as %E0 is not a route
  }
}

export function parseParkPath(pathname: string, search: string): ParkRoute | null {
  if (!isParkPath(pathname)) return null;
  let rest = pathname.slice("/park".length).replace(/^\//, "");
  if (rest.endsWith("/")) rest = rest.slice(0, -1);
  const segments = rest === "" ? ["home"] : rest.split("/");
  const [first, second] = segments;
  if (!isPageId(first)) return null;
  const params: Params = {};
  if (first === "world") {
    if (segments.length !== 2 || !second) return null;
    const id = decodeSegment(second);
    if (id === null || id === "") return null;
    params.id = id;
  } else {
    if (segments.length !== 1) return null;
    const name = QUERY[first];
    const value = name === undefined ? null : new URLSearchParams(search).get(name);
    if (name !== undefined && value) params[name] = value;
  }
  return { page: first, params };
}

export function parkPath(page: PageId, params: Params = {}): string {
  if (page === "world") {
    const id = params.id;
    return id ? `/park/world/${encodeURIComponent(id)}` : "/park/worlds";
  }
  const name = QUERY[page];
  const value = name === undefined ? undefined : params[name];
  if (name === undefined || !value) return `/park/${page}`;
  return `/park/${page}?${new URLSearchParams({ [name]: value }).toString()}`;
}

/** Pushes the path and tells every listener (this app's hook and the Root's) that the address changed. */
export function navigatePark(to: string): void {
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}
const snapshot = (): string => `${window.location.pathname}${window.location.search}`;

/** The current route, re-read on every History API navigation; null when the path is not a Park page. */
export function useParkRoute(): ParkRoute | null {
  const url = useSyncExternalStore(subscribe, snapshot);
  return useMemo(() => {
    const q = url.indexOf("?");
    return q < 0 ? parseParkPath(url, "") : parseParkPath(url.slice(0, q), url.slice(q));
  }, [url]);
}
