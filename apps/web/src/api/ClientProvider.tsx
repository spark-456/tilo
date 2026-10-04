import { type ReactNode, createContext, useContext } from "react";
import type { TiloClient } from "./client";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";

// `VITE_TILO_API_URL` selects the HTTP client (config.ts); the fixture client is the default.
function createDefaultClient(): TiloClient {
  const search = typeof window === "undefined" ? "" : window.location.search;
  return chooseClient({ apiUrl: import.meta.env.VITE_TILO_API_URL, search });
}

const ClientContext = createContext<TiloClient>(createDefaultClient());

export function ClientProvider({
  client,
  children,
}: {
  readonly client: TiloClient;
  readonly children: ReactNode;
}) {
  return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

export const useClient = (): TiloClient => useContext(ClientContext);

/** True while the active client serves fixtures, so every screen shows the HR-4/BQ-07 banner. */
export const useIsFixtureClient = (): boolean => useClient() instanceof FixtureClient;

/** False when the client does not know this world (the fixture client knows one): the screen says
 * "Not found" instead of showing another world's run. Other clients answer unknown ids themselves. */
export function useWorldKnown(worldId: string | null): boolean {
  const client = useClient();
  return worldId === null || !(client instanceof FixtureClient) || client.hasWorld(worldId);
}

/** The fixture client's replay speed (1 for any other client): HR-6 needs a badge when it is not 1. */
export function useReplaySpeed(): number {
  const client = useClient();
  return client instanceof FixtureClient ? client.replaySpeed : 1;
}
