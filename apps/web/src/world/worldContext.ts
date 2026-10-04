// Which world a screen belongs to when its own address does not say (FR-WLD-05, CP2): the world
// screens carry it in the path (/world/:id/...); the Needs-you screens carry it as `?world=<id>`
// (the link from a world's own screens adds it). Without either, the fixture world, the only one
// the fixture client knows, so fixture mode keeps its plain addresses (HR-4 banner says so).
import { useSyncExternalStore } from "react";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";

const IN_PATH = /^\/world\/([^/]+)/;

function decode(raw: string): string | null {
  try {
    return decodeURIComponent(raw);
  } catch {
    return null; // a malformed escape names no world
  }
}

/** The world named by an address: its path first, else `?world=`. Null when it names none. */
export function worldOf(pathname: string, search: string): string | null {
  const raw = IN_PATH.exec(pathname)?.[1];
  const fromPath = raw === undefined ? null : decode(raw);
  if (fromPath) return fromPath;
  const named = new URLSearchParams(search).get("world");
  return named && named.length > 0 ? named : null;
}

/** `path` addressed to `worldId`: unchanged for the fixture world, so fixture addresses stay as they were. */
export const withWorld = (path: string, worldId: string): string =>
  worldId === FIXTURE_WORLD_ID ? path : `${path}?world=${encodeURIComponent(worldId)}`;

/** The same, for a path that already has a query string (`?run=&gate=`). */
export const alsoWorld = (pathWithQuery: string, worldId: string): string =>
  worldId === FIXTURE_WORLD_ID
    ? pathWithQuery
    : `${pathWithQuery}&world=${encodeURIComponent(worldId)}`;

const subscribe = (onChange: () => void) => {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
};
const snapshot = () => `${window.location.pathname}${window.location.search}`;

/** The world of the current address, or null when it names none. Re-read on every navigation. */
export function useAddressedWorld(): string | null {
  const address = useSyncExternalStore(subscribe, snapshot);
  const at = address.indexOf("?");
  return at < 0 ? worldOf(address, "") : worldOf(address.slice(0, at), address.slice(at));
}

/** The world the screen shows: the addressed one, else the fixture world. */
export const useWorldContext = (): string => useAddressedWorld() ?? FIXTURE_WORLD_ID;
