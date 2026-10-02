// CL-INT-3: which TiloClient the app uses. `VITE_TILO_API_URL` (a public origin, never a secret)
// selects the HTTP client; without it the fixture client stays the default for dev and tests.
import type { TiloClient } from "./client";
import { FixtureClient, replaySpeedFromSearch } from "./fixtureClient";
import { HttpClient } from "./http";

export interface ClientConfig {
  readonly apiUrl: string | undefined;
  readonly search: string;
}

/** `?client_delay_ms=N` adds a fixed latency to the fixture client so tests can observe loading
 * and busy states deterministically. */
export function chooseClient({ apiUrl, search }: ClientConfig): TiloClient {
  const url = apiUrl?.trim();
  if (url) return new HttpClient({ baseUrl: url });
  const delay = Number(new URLSearchParams(search).get("client_delay_ms"));
  return new FixtureClient({
    delayMs: Number.isFinite(delay) && delay > 0 ? delay : 0,
    speed: replaySpeedFromSearch(search),
  });
}
