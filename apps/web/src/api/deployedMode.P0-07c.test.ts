// P0-07c: the deployed web app (Firebase Hosting) is built without VITE_TILO_API_URL and must run the
// fixture / replay world with no backend. These tests pin that: with no API origin configured, the client
// is the FixtureClient and the app makes no network request to any API origin.
import { afterEach, describe, expect, it, vi } from "vitest";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("P0-07c: deployed mode (no VITE_TILO_API_URL) is the fixture world", () => {
  it("P0-07c chooseClient returns FixtureClient when the API url is unset, empty or blank", () => {
    for (const apiUrl of [undefined, "", "   "]) {
      const c = chooseClient({ apiUrl, search: "" });
      expect(c).toBeInstanceOf(FixtureClient);
      expect(c).not.toBeInstanceOf(HttpClient);
    }
  });

  it("P0-07c ClientProvider reads the API origin only from VITE_TILO_API_URL and the build leaves it unset", async () => {
    vi.stubEnv("VITE_TILO_API_URL", "");
    const mod = await import("./ClientProvider");
    expect(mod).toBeDefined();
    expect(import.meta.env.VITE_TILO_API_URL ?? "").toBe("");
    expect(chooseClient({ apiUrl: import.meta.env.VITE_TILO_API_URL, search: "" })).toBeInstanceOf(
      FixtureClient,
    );
  });

  it("P0-07c the fixture client makes no network request while replaying a world", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error("P0-07c: no backend in deployed mode");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const client = chooseClient({ apiUrl: undefined, search: "?speed=64" });
    const intake = await client.submitIntake("deploy check", []);
    const approaches = await client.getApproaches(intake.task_id);
    const { world_id } = await client.approve(intake.task_id, {
      approach_id: approaches.recommended,
      budget_cap: approaches.credit_usd,
    });
    await client.getLayout(world_id);
    await client.listCards(world_id);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
