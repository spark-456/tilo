// ONBOARD-1: how "Take the tour" (account menu) reaches the layer. Tiny and eager, so the menu never loads the layer;
// a request made before the layer's chunk has mounted is kept and handed over when it subscribes.
let pending = false;
const listeners = new Set<() => void>();

export function requestTour(): void {
  if (listeners.size === 0) {
    pending = true;
    return;
  }
  for (const l of [...listeners]) l();
}

export function onTourRequest(listener: () => void): () => void {
  listeners.add(listener);
  if (pending) {
    pending = false;
    listener();
  }
  return () => {
    listeners.delete(listener);
  };
}
