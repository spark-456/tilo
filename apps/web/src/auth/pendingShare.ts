// FR-HIL-12: a shared link carries its token in the address. Firebase's sign-in puts the current address in the
// `redirectUrl` it sends to its handler host, so before sign-in starts the token is moved out of the address into
// this tab's sessionStorage and the address becomes plain `/share`; once the person is signed in the token goes back
// into the address and out of storage. Storage holds it for the sign-in only (a few minutes, this tab only), never
// after it is restored. Dependency-free: Root is the entry chunk.
const KEY = "tilo.share.pending";
const KEEP_MS = 15 * 60 * 1000;
const WITH_TOKEN = /^\/share\/([A-Za-z0-9_-]{16,128})\/?$/;
const BARE = /^\/share\/?$/;

function read(): { t: string; at: number } | null {
  try {
    const v: unknown = JSON.parse(window.sessionStorage.getItem(KEY) ?? "null");
    const o = v as { t?: unknown; at?: unknown } | null;
    return o && typeof o.t === "string" && typeof o.at === "number" ? { t: o.t, at: o.at } : null;
  } catch {
    return null;
  }
}

const clear = (): void => {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // storage may be blocked; nothing was stored then
  }
};

/** Before sign-in: on `/share/<token>` keep the token aside and make the address `/share`. Anywhere else, nothing. */
export function stashShareToken(now: number = Date.now()): void {
  const m = WITH_TOKEN.exec(window.location.pathname);
  if (!m?.[1]) return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ t: m[1], at: now }));
  } catch {
    return; // no storage: leave the address as it is rather than lose the link
  }
  window.history.replaceState(window.history.state, "", "/share");
}

/** After sign-in: on `/share` with a fresh kept token, put it back in the address and drop it from storage. */
export function restoreShareToken(now: number = Date.now()): void {
  if (!BARE.test(window.location.pathname)) return;
  const kept = read();
  clear();
  if (!kept || now - kept.at > KEEP_MS || !/^[A-Za-z0-9_-]{16,128}$/.test(kept.t)) return;
  window.history.replaceState(window.history.state, "", `/share/${kept.t}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
