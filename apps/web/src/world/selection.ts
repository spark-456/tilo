// FR-WLD-06: the one selection of a run, shared by the World stage and outline, Story, Trace and
// Inspect. It is display state only (which object the person is following): it records nothing,
// moves nothing and is never an event (HR-1, HR-3). Held per world, so one run's selection never
// shows in another's, and kept for the page's lifetime, so moving between lenses keeps it.
import type { Event, Layout } from "@tilo/contracts";
import { useCallback, useSyncExternalStore } from "react";

const chosen = new Map<string, string>();
const listeners = new Set<() => void>();

export const getSelection = (worldId: string): string | null => chosen.get(worldId) ?? null;

export function subscribeSelection(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

/** Selects `id` in this world (null clears). The same id again changes nothing. */
export function select(worldId: string, id: string | null): void {
  if (getSelection(worldId) === id) return;
  if (id === null) chosen.delete(worldId);
  else chosen.set(worldId, id);
  for (const listener of [...listeners]) listener();
}

/** The world's selected id and a setter that toggles: choosing the selected id again clears it. */
export function useSelection(
  worldId: string,
): readonly [string | null, (id: string | null) => void, (id: string) => void] {
  const id = useSyncExternalStore(subscribeSelection, () => getSelection(worldId));
  const set = useCallback((next: string | null) => select(worldId, next), [worldId]);
  const toggle = useCallback(
    (next: string) => select(worldId, getSelection(worldId) === next ? null : next),
    [worldId],
  );
  return [id, set, toggle];
}

/** Whether the event names this object: as actor or target, as the item it carries, or as the
 * level or district it was recorded in. Read from the event's own fields, never guessed. */
export const involves = (e: Event, id: string): boolean =>
  e.actor === id ||
  e.target === id ||
  e.item?.artifact_id === id ||
  e.level === id ||
  e.district === id;

/** Every id of an object the world shows: agents, levels, districts, buildings, islands (from the
 * layout) and artifacts (from the events that carry them). People and gates are not objects. */
export function objectIds(layout: Layout, events: readonly Event[]): ReadonlySet<string> {
  const ids = new Set<string>(layout.semantic.agents.map((a) => a.id));
  for (const island of layout.semantic.islands) ids.add(island.id);
  for (const level of layout.semantic.levels) {
    ids.add(level.id);
    for (const district of level.districts) {
      ids.add(district.id);
      for (const building of district.buildings) ids.add(building.id);
    }
  }
  for (const e of events) if (e.item?.artifact_id) ids.add(e.item.artifact_id);
  return ids;
}
