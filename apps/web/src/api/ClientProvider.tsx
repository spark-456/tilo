import { type ReactNode, createContext, useContext, useSyncExternalStore } from "react";
import { createAppCheckTokenGetter } from "../appcheck/appCheck";
import { session } from "../auth/session";
import type { SessionView } from "../park/api/select";
import type { TiloClient } from "./client";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

/** The one reader of `VITE_TILO_API_URL` (repo test P0-07c); the Park app takes it from here. */
export const API_URL: string | undefined = import.meta.env.VITE_TILO_API_URL;

/** SEC-10: the App Check token getter for this page's host, shared by the app's client and the Park app's own
 * (`park/app/context.tsx` takes it from here). Nothing starts until a request asks for a token, so the fixture
 * world never loads reCAPTCHA, and a local host answers null with no call. */
export const appCheckToken: (() => Promise<string | null>) | undefined =
  typeof window === "undefined"
    ? undefined
    : createAppCheckTokenGetter({ hostname: window.location.hostname });

/** SEC-15: the Firebase ID token getter for this page's one sign-in session, shared like `appCheckToken`. Null when
 * nobody is signed in, on a local host and in a build with no Firebase config (no SDK is loaded then). */
export const authToken: (() => Promise<string | null>) | undefined =
  typeof window === "undefined" ? undefined : () => session.idToken();

/** Today by the person's own clock, as a calendar date: the sample company's dates follow it (park/api/sampleDates.ts). */
export const civilToday = (): { y: number; m: number; d: number } => {
  const now = new Date();
  return { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() };
};

/** Who is signed in, read at call time from the one sign-in session (LIVE-HOME). */
export const sessionView: SessionView = {
  now: () => new Date(),
  demo: () => session.getState().status === "anonymous",
  identity: () => {
    const state = session.getState();
    return state.status === "google" ? { name: state.displayName, email: state.email } : null;
  },
};

// `VITE_TILO_API_URL` selects the HTTP client (config.ts); the fixture client is the default.
function createDefaultClient(): TiloClient {
  const search = typeof window === "undefined" ? "" : window.location.search;
  return chooseClient({ apiUrl: API_URL, search, appCheckToken, authToken });
}

const defaultClient = createDefaultClient();
const ClientContext = createContext<TiloClient>(defaultClient);

/** DEMO-FIXTURES-1: a demo (anonymous) session reads the fixture world everywhere, never the API: the server refuses a
 * demo without a declaration and a demo stores nothing and calls no real model. Only the default client is swapped; a
 * client a provider or a test supplied is the caller's choice. */
export function clientFor(
  current: TiloClient,
  demo: TiloClient,
  status: string,
  isDefault: TiloClient,
): TiloClient {
  return status === "anonymous" && current === isDefault ? demo : current;
}

let demoClient: TiloClient | null = null;
const demoFixture = (): TiloClient => {
  const search = typeof window === "undefined" ? "" : window.location.search;
  demoClient ??= chooseClient({ apiUrl: undefined, search });
  return demoClient;
};

export function ClientProvider({
  client,
  children,
}: {
  readonly client: TiloClient;
  readonly children: ReactNode;
}) {
  return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

/** The context's client, or the fixture client for a demo session when it is the default (`isDefault`). */
export function useSessionClient(context: TiloClient, isDefault: TiloClient): TiloClient {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  return clientFor(
    context,
    state.status === "anonymous" ? demoFixture() : context,
    state.status,
    isDefault,
  );
}

export const useClient = (): TiloClient =>
  useSessionClient(useContext(ClientContext), defaultClient);

/** True while the active client serves fixtures, so every screen shows the HR-4/BQ-07 banner. */
export const useIsFixtureClient = (): boolean => useClient() instanceof FixtureClient;

const never = () => () => undefined;

/** False when the client does not know this world: the screen says "Not found" instead of showing
 * another world's run. The fixture client knows one; the HTTP client learns it is unknown from the
 * 404 of the world's events (and stops polling it). Other clients answer unknown ids themselves. */
export function useWorldKnown(worldId: string | null): boolean {
  const client = useClient();
  const http = client instanceof HttpClient ? client : null;
  const missing = useSyncExternalStore(
    http ? (onChange) => http.onWorldMissing(onChange) : never,
    () => (http !== null && worldId !== null ? http.isWorldMissing(worldId) : false),
  );
  if (worldId === null) return true;
  if (client instanceof FixtureClient) return client.hasWorld(worldId);
  return !missing;
}

/** The fixture client's replay speed (1 for any other client): HR-6 needs a badge when it is not 1. */
export function useReplaySpeed(): number {
  const client = useClient();
  return client instanceof FixtureClient ? client.replaySpeed : 1;
}
