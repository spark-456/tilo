import { type ReactNode, createContext, useContext, useMemo } from "react";
import type { TiloClient } from "./client";
import { FixtureClient } from "./fixtureClient";

const defaultClient = new FixtureClient();
const ClientContext = createContext<TiloClient>(defaultClient);

export function ClientProvider({
  client,
  children,
}: {
  readonly client?: TiloClient;
  readonly children: ReactNode;
}) {
  const value = useMemo(() => client ?? defaultClient, [client]);
  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>;
}

export function useTiloClient(): TiloClient {
  return useContext(ClientContext);
}
