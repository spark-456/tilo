// @vitest-environment happy-dom
// DEMO-FIXTURES-1 (supervisor 9 Oct, matches #644 and DEMO-EPHEMERAL): a demo (anonymous) session reads the fixture
// world everywhere, the kept screens (/start, the stage) included. It is never asked the sign-up question and never
// calls a gated route: the server refuses a demo without a declaration, and a demo "stores nothing, never calls real
// models". A Google sign-in keeps the HTTP client; a local host or a build with no Firebase config (no sign-in UI)
// keeps whatever the default client is.
import { describe, expect, it, vi } from "vitest";
import { liveWorldsReader } from "../onboarding/sampleWorld";
import { clientFor } from "./ClientProvider";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

const http = new HttpClient({ baseUrl: "https://api.example.test" });
const fixture = new FixtureClient({ delayMs: 0, speed: 1 });

describe("DEMO-FIXTURES-1 which client a session gets", () => {
  it("DEMO-FIXTURES-1 an anonymous demo session gets the fixture client, not the HTTP one", () => {
    expect(clientFor(http, fixture, "anonymous")).toBe(fixture);
  });

  it.each(["google", "signed_out", "unknown", "unavailable"])(
    "DEMO-FIXTURES-1 a %s session keeps the default client",
    (status) => {
      expect(clientFor(http, fixture, status)).toBe(http);
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
