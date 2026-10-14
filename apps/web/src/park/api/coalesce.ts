// JUDGE-FIRST-RUN F6: one read in flight is shared by everyone who asks for it while it is out. A page, the shell and the
// first-run check each ask for the worlds list and the cards when a page loads; the server is asked once, and all of
// them get that one answer. Nothing is kept after it settles (the next ask is a fresh read), so a result is never older
// than the read it joined, and a failed read is not remembered.
export function coalesce<K extends string, T>(
  read: (key: K) => Promise<T>,
): (key: K) => Promise<T> {
  const inFlight = new Map<K, Promise<T>>();
  return (key) => {
    const out = inFlight.get(key);
    if (out) return out;
    const started = read(key).finally(() => {
      if (inFlight.get(key) === started) inFlight.delete(key);
    });
    inFlight.set(key, started);
    return started;
  };
}
