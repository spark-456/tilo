// TILO-T-WORLD: the stage's display state that is not the selection: which agent the pointer is over, which agents a
// clicked message lights up, which agent's panel is open, and the camera's fly-to. All of it is held per world, is
// never an event and moves nothing in the world (HR-1, HR-3); the camera's own easing stays the Stage's.
import { useSyncExternalStore } from "react";

export interface Spotlight {
  /** The agent under the pointer (lit, with its stats card at `point`), or null. */
  readonly hover: string | null;
  /** The pointer, in px from the stage's top-left corner; null when nothing is hovered. */
  readonly point: { readonly x: number; readonly y: number } | null;
  /** Agents lit by a clicked message (sender and receiver), until something else is chosen. */
  readonly lit: readonly string[];
  /** The agent whose panel is open ("Talk to"), or null. */
  readonly opened: string | null;
}

const EMPTY: Spotlight = { hover: null, point: null, lit: [], opened: null };
const held = new Map<string, Spotlight>();
const listeners = new Set<() => void>();

export const getSpotlight = (worldId: string): Spotlight => held.get(worldId) ?? EMPTY;

export function subscribeSpotlight(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function put(worldId: string, next: Spotlight): void {
  const was = getSpotlight(worldId);
  if (
    was.hover === next.hover &&
    was.opened === next.opened &&
    was.point?.x === next.point?.x &&
    was.point?.y === next.point?.y &&
    was.lit.length === next.lit.length &&
    was.lit.every((id, i) => id === next.lit[i])
  )
    return;
  held.set(worldId, next);
  for (const listener of [...listeners]) listener();
}

export function setHover(
  worldId: string,
  id: string | null,
  point: { x: number; y: number } | null,
): void {
  put(worldId, { ...getSpotlight(worldId), hover: id, point: id === null ? null : point });
}

export function setLit(worldId: string, ids: readonly string[]): void {
  put(worldId, { ...getSpotlight(worldId), lit: ids });
}

export function openAgent(worldId: string, id: string | null): void {
  put(worldId, { ...getSpotlight(worldId), opened: id });
}

export function resetSpotlights(): void {
  held.clear();
  flyListeners.clear();
  probes.clear();
  for (const listener of [...listeners]) listener();
}

export function useSpotlight(worldId: string): Spotlight {
  return useSyncExternalStore(
    subscribeSpotlight,
    () => getSpotlight(worldId),
    () => EMPTY,
  );
}

/** What the drawn stage can tell the page: the agent under a point and where an id stands, both in px from the
 * stage's top-left corner (the Pixi world's own transform, so they follow the camera). */
export interface Probe {
  agentAt(x: number, y: number): string | null;
  locate(id: string): { x: number; y: number } | null;
}
const probes = new Map<string, Probe>();
export const registerProbe = Object.assign(
  (worldId: string, probe: Probe): (() => void) => {
    probes.set(worldId, probe);
    return () => {
      if (probes.get(worldId) === probe) probes.delete(worldId);
    };
  },
  { get: (worldId: string): Probe | undefined => probes.get(worldId) },
);

type FlyListener = (target: string, ms: number) => void;
const flyListeners = new Map<string, Set<FlyListener>>();

/** Lets the Stage of `worldId` hear camera fly-to requests. */
export function onFly(worldId: string, listener: FlyListener): () => void {
  const set = flyListeners.get(worldId) ?? new Set<FlyListener>();
  set.add(listener);
  flyListeners.set(worldId, set);
  return () => set.delete(listener);
}

/** Asks the world's camera to centre on an agent or a building: display only. `ms` is the glide (the design's
 * Story click is 900 ms with the standard easing). */
export function flyTo(worldId: string, target: string, ms = 900): void {
  for (const listener of [...(flyListeners.get(worldId) ?? [])]) listener(target, ms);
}
