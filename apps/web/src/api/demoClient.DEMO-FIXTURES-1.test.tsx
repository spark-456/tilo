// @vitest-environment happy-dom
// DEMO-FIXTURES-1 (supervisor 9 Oct, matches #644 and DEMO-EPHEMERAL): a demo (anonymous) session reads the fixture
// world everywhere, the kept screens (/start, the stage) included. It is never asked the sign-up question and never
// calls a gated route: the server refuses a demo without a declaration, and a demo "stores nothing, never calls real
// models". A Google sign-in keeps the HTTP client; a local host or a build with no Firebase config (no sign-in UI)
// keeps whatever the default client is.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { liveWorldsReader } from "../onboarding/sampleWorld";
import { clientFor, useSessionClient } from "./ClientProvider";
import type { TiloClient } from "./client";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

const session = vi.hoisted(() => ({ status: "anonymous" as string, states: {} as Record<string, { status: string }> }));
vi.mock("../auth/session", () => ({
  session: { getState: () => (session.states[session.status] ??= { status: session.status }), // one object per status: a stable snapshot subscribe: () => () => undefined },
}));

const http = new HttpClient({ baseUrl: "https://api.example.test" });
const fixture = new FixtureClient({ delayMs: 0, speed: 1 });

describe("DEMO-FIXTURES-1 which client a session gets", () => {
  it("DEMO-FIXTURES-1 an anonymous demo session gets the fixture client, not the HTTP one", () => {
    expect(clientFor(http, fixture, "anonymous", http)).toBe(fixture);
  });

  it.each(["google", "signed_out", "unknown", "unavailable"])(
    "DEMO-FIXTURES-1 a %s session keeps the default client",
    (status) => {
      expect(clientFor(http, fixture, status, http)).toBe(http);
    },
  );

  it("DEMO-FIXTURES-1 a client a caller chose on purpose (a test or provider) is never swapped", () => {
    const own = new FixtureClient({ delayMs: 0, speed: 1 });
    expect(clientFor(own, fixture, "anonymous", http)).toBe(own);
  });
});

describe("DEMO-FIXTURES-1 the tour never reads the worlds list for a demo session", () => {
  it("DEMO-FIXTURES-1 a demo has no worlds reader and no request is made", () => {
    const spy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network in a demo"));
    expect(liveWorldsReader("anonymous")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("DEMO-FIXTURES-1 the hook the screens call", () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  function seen(context: TiloClient, isDefault: TiloClient, status: string): TiloClient {
    session.status = status;
    let got: TiloClient | null = null;
    function Probe() {
      got = useSessionClient(context, isDefault);
      return null;
    }
    const root = createRoot(document.createElement("div"));
    act(() => root.render(<Probe />));
    act(() => root.unmount());
    return got as unknown as TiloClient;
  }

  it("DEMO-FIXTURES-1 a demo session's screens get a fixture client, and a Google session's keep the HTTP one", () => {
    expect(seen(http, http, "anonymous")).toBeInstanceOf(FixtureClient);
    expect(seen(http, http, "google")).toBe(http);
  });

  it("DEMO-FIXTURES-1 a client a provider supplied is never swapped, even for a demo", () => {
    const own = new FixtureClient({ delayMs: 0, speed: 1 });
    expect(seen(own, http, "anonymous")).toBe(own);
  });
});
