// UX-SMOOTH: a started run is not an Api write (the one-step start is its own reader), so the stale-while-revalidate
// cache (swr.ts) would answer the World page with a world list read before the run existed. Each cache registers how
// to forget itself here, and a successful start forgets them all, so the page opening the new world reads it fresh.
const forgets = new Set<() => void>();

/** Called by a read cache; returns the unregister. */
export function onForgetReads(forget: () => void): () => void {
  forgets.add(forget);
  return () => forgets.delete(forget);
}

/** Forgets every cached read: the next read of each goes to the server. */
export function forgetReads(): void {
  for (const forget of forgets) forget();
}
