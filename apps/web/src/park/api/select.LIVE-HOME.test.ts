// LIVE-HOME (live build on tilo-dev showed "Not connected yet" everywhere after sign-in): the Park Api for a
// deployment with an API url. A demo (anonymous) session reads the fixture company and makes no request; a Google
// session gets the live Api plus the two reads that need no endpoint (who is signed in, what day it is).
import { afterEach, describe, expect, it, vi } from "vitest";
import * as fx from "./fixtures";
import { NotBuilt } from "./liveApi";
import { parkApi, withSession } from "./select";

const LIVE_ENV = { VITE_TILO_API_URL: "https://api.example.test" };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LIVE-HOME demo session", () => {
  it("LIVE-HOME a demo session reads the fixture Api and makes no network request", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const api = withSession(parkApi(LIVE_ENV), {
      now: () => new Date(),
      demo: () => true,
      identity: () => null,
    });
    const user = await api.getUser();
    expect(user.source).toBe("fixture");
    expect(user.data).toEqual(fx.user);
    expect((await api.getLedger()).source).toBe("fixture");
    expect((await api.getSkills()).data).toEqual(fx.skills);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("LIVE-HOME a signed-in person is not shown the fixture company", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 401 })),
    );
    const api = withSession(parkApi(LIVE_ENV), {
      now: () => new Date(),
      demo: () => false,
      identity: () => ({ name: "Riya Sharma", email: "riya@example.org" }),
    });
    await expect(api.getAgenda()).rejects.toBeInstanceOf(NotBuilt);
  });
});

describe("LIVE-HOME signed-in reads that need no endpoint", () => {
  const live = () =>
    withSession(parkApi(LIVE_ENV), {
      now: () => new Date(),
      demo: () => false,
      identity: () => ({ name: "Riya Sharma", email: "riya@example.org" }),
    });

  it("LIVE-HOME getUser is the signed-in person, live, with nothing invented", async () => {
    const { data, source } = await live().getUser();
    expect(source).toBe("live");
    expect(data.first).toBe("Riya");
    expect(data.name).toBe("Riya Sharma");
    expect(data.initials).toBe("RS");
    expect(data.email).toBe("riya@example.org");
    expect(JSON.stringify(data)).not.toContain(fx.user.org);
    expect(JSON.stringify(data)).not.toContain(fx.user.title);
  });

  it("LIVE-HOME a person with no display name is greeted by the start of the email", async () => {
    const api = withSession(parkApi(LIVE_ENV), {
      now: () => new Date(),
      demo: () => false,
      identity: () => ({ name: null, email: "riya.sharma@example.org" }),
    });
    const { data } = await api.getUser();
    expect(data.first).toBe("Riya");
    expect(data.email).toBe("riya.sharma@example.org");
  });

  it("LIVE-HOME getToday reads the clock", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-08T09:12:00"));
    try {
      const { data, source } = await live().getToday();
      expect(source).toBe("live");
      expect(data.long).toBe("Thursday 8 October");
      expect(data.short).toBe("Thu 8 Oct");
      expect(data.time).toBe("09:12");
    } finally {
      vi.useRealTimers();
    }
  });

  it("LIVE-HOME nobody signed in means getUser is not built, not a made-up person", async () => {
    const api = withSession(parkApi(LIVE_ENV), {
      now: () => new Date(),
      demo: () => false,
      identity: () => null,
    });
    await expect(api.getUser()).rejects.toBeInstanceOf(NotBuilt);
  });
});
