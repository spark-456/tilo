import { describe, expect, it, vi } from "vitest";
import { createLiveApi } from "./liveApi";
import { withSession } from "./select";

describe("LIVE_WIRING_1 local profile", () => {
  it("LIVE_WIRING_1 returns unavailable billing and sessions without fetching", async () => {
    const fetch = vi.fn();
    const api = createLiveApi({ baseUrl: "https://api.example", fetch });
    const result = await api.getProfileSettings();
    expect(result.source).toBe("live");
    expect(result.data).toMatchObject({
      sessions: null,
      invoices: null,
      payment: null,
      plan: null,
    });
    expect(result.data.notifications.find((n) => n.id === "decisions")).toMatchObject({
      phone: true,
      email: true,
      slack: true,
    });
    expect(result.data.quiet).toEqual({
      on: true,
      start: "19:00",
      end: "08:00",
      threshold: "",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("LIVE_WIRING_1 keeps preferences in one instance and returns independent copies", async () => {
    const fetch = vi.fn();
    const api = createLiveApi({ baseUrl: "https://api.example", fetch });
    expect(await api.setPref("quiet", false)).toEqual({ data: { ok: true }, source: "live" });
    const first = (await api.getProfileSettings()).data;
    expect(first.quiet.on).toBe(false);
    const decision = first.notifications[0];
    if (!decision) throw new Error("Missing decision defaults");
    decision.phone = false;
    first.quiet.start = "changed";
    expect((await api.getProfileSettings()).data.notifications[0]?.phone).toBe(true);
    expect((await api.getProfileSettings()).data.quiet.start).toBe("19:00");
    expect(
      (await createLiveApi({ baseUrl: "https://api.example", fetch }).getProfileSettings()).data
        .quiet.on,
    ).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("LIVE_WIRING_1 reads name and email through the existing session view", async () => {
    const api = withSession(createLiveApi({ baseUrl: "https://api.example" }), {
      demo: () => false,
      identity: () => ({ name: "Ana Silva", email: "ana@example.test" }),
      now: () => new Date("2026-10-09T00:00:00Z"),
    });
    expect((await api.getUser()).data).toMatchObject({
      name: "Ana Silva",
      email: "ana@example.test",
    });
  });
});
