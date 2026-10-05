/** A code-split chunk did not load (offline, or a deploy replaced its name). A browser keeps a failed
 * dynamic import for the life of the page, so asking again in place cannot work: the caller says so
 * and offers a reload (NFR-01). */
export class ChunkLoadError extends Error {
  constructor(what: string) {
    super(`${what} did not load`);
    this.name = "ChunkLoadError";
  }
}
