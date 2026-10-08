// How many links the Park app has followed (FR-UX-12). The address does not change when a link names the address
// you are already on, so a page that keeps its own state apart from the address (Profile opens a tab by hand) could
// not hear that the link was followed. This counter is that signal. It is NOT part of the route: the route, and so
// every page's `app`, stays the same for such a link, because a page that redirects in an effect would loop if a
// followed link to its own address counted as a change. Only a page that asks (`useFollowed`) re-renders.
import { useSyncExternalStore } from "react";

let followed = 0;
const listeners = new Set<() => void>();

/** The router's side: a link was followed (also one to the address the person is already on). */
export function noteFollowed(): void {
  followed += 1;
  for (const on of [...listeners]) on();
}

function subscribe(on: () => void): () => void {
  listeners.add(on);
  return () => {
    listeners.delete(on);
  };
}

/** A page's side: changes whenever a link is followed. Use it only as a hint to re-read the address's query. */
export function useFollowed(): number {
  return useSyncExternalStore(subscribe, () => followed);
}
