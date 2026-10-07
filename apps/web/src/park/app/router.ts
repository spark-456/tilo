// The Park router (README "Routes"; plan sections 1 and 3): the pages live at the ROOT paths (/, /worlds,
// /world/:id, /team, ...) and /park/<page> stays as an alias. Pure path functions plus one hook. This is
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

// Root pages other than home ("/" is home, the world page takes exactly one id segment).
const ROOT_PAGES = new Set<string>([
  "worlds",
  "team",
  "connectors",
  "skills",
  "agenda",
  "ledger",
  "profile",
]);
const ROOT_WORLD = /^\/world\/[^/]+\/?$/;

/**
 * The live stage (S-04) of a world: an old-app address next to the Park pages (`/world/:id` is the Park overview).
 * The same string as `stagePath` in src/router.ts (router.test.ts pins that); park/ imports nothing from there.
 */
export const stagePath = (worldId: string): string => `/world/${encodeURIComponent(worldId)}/stage`;

/**
 * The ONE predicate for "this address is served by the Park app": the root Park paths and the /park alias.
 * Paths the old app keeps (/world/:id/stage, /team/console, /worlds/replays, ...) are not Park paths.
 */
export function isParkPath(pathname: string): boolean {
  if (pathname === "/park" || pathname.startsWith("/park/") || pathname === "/") return true;
  if (ROOT_WORLD.test(pathname)) return true;
  const m = /^\/([^/]+)\/?$/.exec(pathname);
  return m?.[1] !== undefined && ROOT_PAGES.has(m[1]);
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
  let rest =
    pathname === "/park" || pathname.startsWith("/park/")
      ? pathname.slice("/park".length)
      : pathname;
  rest = rest.replace(/^\//, "");
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

/** The address a page is written at: always the ROOT path, never the /park alias. */
export function parkPath(page: PageId, params: Params = {}): string {
  if (page === "world") {
    const id = params.id;
    return id ? `/world/${encodeURIComponent(id)}` : "/worlds";
  }
  const base = page === "home" ? "/" : `/${page}`;
  const name = QUERY[page];
  const value = name === undefined ? undefined : params[name];
  if (name === undefined || !value) return base;
  return `${base}?${new URLSearchParams({ [name]: value }).toString()}`;
}

/** True when the address bar is on the Park Home page: the landing visit, whose page chunk starts with the shell's. */
export function isHomeAddress(): boolean {
  if (typeof window === "undefined") return false;
  return parseParkPath(window.location.pathname, window.location.search)?.page === "home";
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
