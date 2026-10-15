// The Park router (README "Routes"; plan sections 1 and 3): the pages live at the ROOT paths (/, /worlds,
// /world/:id, /team, ...) and /park/<page> stays as an alias. Pure path functions plus one hook. This is
// the only file under park/ that reads the address bar; pages get `app.page` and `app.params`.
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { PAGE_IDS, type PageId, type Params } from "./AppCtx";
import { adminRedirect } from "./adminRedirect";
import { noteFollowed } from "./followed";

export interface ParkRoute {
  page: PageId;
  params: Params;
}

// The query names each page keeps (README "Routes"); anything else is dropped. The world id is a path
// segment, not a query value.
const QUERY: Partial<Record<PageId, string>> = {
  skills: "id",
  team: "focus",
  profile: "tab",
  settings: "section",
};

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
  "settings",
  "library",
  "more",
  "chat",
]);
const ROUTINES_ADDRESS = /^\/(?:park\/)?routines\/?$/;
const ROOT_WORLD = /^\/world\/[^/]+\/?$/;
const ROOT_WORLD_APP = /^\/(?:park\/)?world\/([^/]+)\/app\/([^/]+)\/?$/;

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
  if (adminRedirect(pathname)) return true;
  if (pathname === "/park" || pathname.startsWith("/park/") || pathname === "/") return true;
  if (ROUTINES_ADDRESS.test(pathname)) return true;
  if (ROOT_WORLD.test(pathname) || ROOT_WORLD_APP.test(pathname)) return true;
  const m = /^\/([^/]+)\/?$/.exec(pathname);
  return m?.[1] !== undefined && ROOT_PAGES.has(m[1]);
}

/**
 * OLD-UI-OUT wave 3: the addresses of the removed old screens (Meeting, Meetings, My plate, Pinboards, Calendar, the
 * Library's version history, Worlds replays), each answered by the Park page that took its function, so an old link
 * never lands on "Page not found". The address is replaced in the history, never pushed.
 */
const LEGACY: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/library\/artifacts\/?$/, "/library"],
  [/^\/meetings?(?:\/[^/]+)?\/?$/, "/agenda"],
  [/^\/(?:pinboards|calendar)\/?$/, "/agenda"],
  [/^\/plate\/?$/, "/"],
  [/^\/worlds\/replays\/?$/, "/worlds"],
];

/** The Park address that now holds what `pathname` used to, or null when it is not a removed old address. */
export function legacyTarget(pathname: string): string | null {
  for (const [re, to] of LEGACY) if (re.test(pathname)) return to;
  return null;
}

function decodeSegment(raw: string): string | null {
  try {
    return decodeURIComponent(raw);
  } catch {
    return null; // a malformed escape such as %E0 is not a route
  }
}

export function parseParkPath(pathname: string, search: string): ParkRoute | null {
  const redirect = adminRedirect(pathname, search);
  if (redirect) {
    const at = redirect.indexOf("?");
    return parseParkPath(
      at < 0 ? redirect : redirect.slice(0, at),
      at < 0 ? "" : redirect.slice(at),
    );
  }
  if (ROUTINES_ADDRESS.test(pathname)) return { page: "worlds", params: {} };
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
    const world = new URLSearchParams(search).get("world");
    if (world && (first === "settings" || first === "team" || first === "connectors"))
      params.world = world;
  }
  if (["team", "connectors", "more"].includes(first)) {
    const world = new URLSearchParams(search).get("world");
    if (world) params.world = world;
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
  const query = new URLSearchParams();
  if (name !== undefined && value) query.set(name, value);
  if (params.world && ["settings", "team", "connectors", "more"].includes(page))
    query.set("world", params.world);
  return query.size ? `${base}?${query}` : base;
}

/** True when the address bar is on the Park Home page: the landing visit, whose page chunk starts with the shell's. */
export function isHomeAddress(): boolean {
  if (typeof window === "undefined") return false;
  return parseParkPath(window.location.pathname, window.location.search)?.page === "home";
}

/**
 * UI-10 B6: the one recorded run the demo can replay: the bundled `village-basic` stream (a mail-room reply run,
 * plan to delivery) on the stage, which labels it "Fixture replay". It is a recording, never the person's own task.
 */
export const RECORDED_RUN_PATH = `${stagePath("w_village_basic")}?fixture=village-basic`;

/** Pushes the path and tells every listener (this app's hook and the Root's) that the address changed. */
export function navigatePark(to: string): void {
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  noteFollowed(); // after the route has updated: a page reading the address then reads the new one
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}
const snapshot = (): string => `${window.location.pathname}${window.location.search}`;

/** The current route, re-read on every History API navigation; null when the path is not a Park page. */
export function useParkRoute(): ParkRoute | null {
  const url = useSyncExternalStore(subscribe, snapshot);
  const legacy = ROUTINES_ADDRESS.test(url.split("?")[0] ?? "")
    ? "/worlds"
    : legacyTarget(url.split("?")[0] ?? url);
  useEffect(() => {
    if (legacy === null) return;
    window.history.replaceState({}, "", legacy);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [legacy]);
  return useMemo(() => {
    const at = legacy ?? url;
    const q = at.indexOf("?");
    return q < 0 ? parseParkPath(at, "") : parseParkPath(at.slice(0, q), at.slice(q));
  }, [url, legacy]);
}

export interface QuizAppRoute {
  readonly worldId: string;
  readonly artifactId: string;
}

export function parseQuizAppPath(pathname: string): QuizAppRoute | null {
  const m = ROOT_WORLD_APP.exec(pathname);
  if (!m?.[1] || !m?.[2]) return null;
  const worldId = decodeSegment(m[1]);
  const artifactId = decodeSegment(m[2]);
  if (!worldId || !artifactId) return null;
  return { worldId, artifactId };
}

export function useQuizAppRoute(): QuizAppRoute | null {
  const url = useSyncExternalStore(subscribe, snapshot);
  return useMemo(() => {
    const q = url.indexOf("?");
    const pathname = q < 0 ? url : url.slice(0, q);
    return parseQuizAppPath(pathname);
  }, [url]);
}
