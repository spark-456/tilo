import { type ReactNode, createContext, useContext } from "react";
import type { TiloClient } from "./client";
import { FixtureClient, replaySpeedFromSearch } from "./fixtureClient";

// The fixture client is the default until CL-INT adds src/api/http.ts. `?client_delay_ms=N` adds
// a fixed latency to it so tests can observe loading and busy states deterministically.
function createDefaultClient(): TiloClient {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const delay = Number(new URLSearchParams(search).get("client_delay_ms"));
  return new FixtureClient({
    delayMs: Number.isFinite(delay) && delay > 0 ? delay : 0,
    speed: replaySpeedFromSearch(search),
  });
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
