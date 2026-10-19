// SEC-10: the parts of App Check start-up the pinned tests do not cover: a build with no Firebase web config skips
// App Check (one console line, the app still works), a token request that hangs gives up after TOKEN_TIMEOUT_MS,
// and nothing is started until the first token request. The Firebase SDK is a fake: no network.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => {
  class ReCaptchaEnterpriseProvider {
    constructor(readonly siteKey: string) {}
  }
  return {
    ReCaptchaEnterpriseProvider,
    initializeApp: vi.fn((options: unknown) => ({ options })),
    initializeAppCheck: vi.fn((_app: unknown, _options: unknown) => ({ appCheck: true })),
    getToken: vi.fn(async (_appCheck: unknown, _force?: boolean) => ({ token: "fake-token" })),
  };
});

vi.mock("firebase/app", () => ({ initializeApp: sdk.initializeApp }));
const workingAppCheck = () => ({
  initializeAppCheck: sdk.initializeAppCheck,
  getToken: sdk.getToken,
  ReCaptchaEnterpriseProvider: sdk.ReCaptchaEnterpriseProvider,
});
vi.mock("firebase/app-check", () => workingAppCheck());

const DEPLOYED = "example-project.web.app";

async function load() {
  vi.resetModules();
  return (await import("./appCheck")) as typeof import("./appCheck");
}

beforeEach(() => {
  for (const fn of [sdk.initializeApp, sdk.initializeAppCheck, sdk.getToken]) fn.mockClear();
  sdk.getToken.mockImplementation(async () => ({ token: "fake-token" }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("SEC-10 a build with no Firebase web config skips App Check", () => {
  it("SEC-10 a missing or empty VITE_FIREBASE_API_KEY or VITE_FIREBASE_PROJECT_ID resolves null and starts nothing", async () => {
    for (const [name, value] of [
      ["VITE_FIREBASE_API_KEY", undefined],
      ["VITE_FIREBASE_API_KEY", ""],
      ["VITE_FIREBASE_PROJECT_ID", undefined],
      ["VITE_FIREBASE_PROJECT_ID", ""],
    ] as const) {
      vi.unstubAllEnvs();
      vi.stubEnv(name, value as string);
      vi.spyOn(console, "info").mockImplementation(() => undefined);
      const { createAppCheckTokenGetter } = await load();
      await expect(createAppCheckTokenGetter({ hostname: DEPLOYED })()).resolves.toBeNull();
      expect(sdk.initializeApp, `${name}=${String(value)}`).not.toHaveBeenCalled();
      expect(sdk.initializeAppCheck).not.toHaveBeenCalled();
    }
  });

  it("SEC-10 the skip is said once, as info (not an error or warning), however many calls follow", async () => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const bad = [
      vi.spyOn(console, "error").mockImplementation(() => undefined),
      vi.spyOn(console, "warn").mockImplementation(() => undefined),
    ];
    const { createAppCheckTokenGetter } = await load();
    const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });
    await getter();
    await getter();
    await createAppCheckTokenGetter({ hostname: DEPLOYED })();
    expect(info).toHaveBeenCalledTimes(1);
    for (const spy of bad) expect(spy).not.toHaveBeenCalled();
  });

  it("SEC-10 a local host with no config says nothing at all", async () => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const { createAppCheckTokenGetter } = await load();
    await createAppCheckTokenGetter({ hostname: "localhost" })();
    expect(info).not.toHaveBeenCalled();
  });
});

describe("SEC-10 start-up is lazy and bounded", () => {
  it("SEC-10 building the getter starts nothing; the first token request does", async () => {
    const { createAppCheckTokenGetter } = await load();
    const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });
    expect(sdk.initializeApp).not.toHaveBeenCalled();
    expect(sdk.initializeAppCheck).not.toHaveBeenCalled();
    await expect(getter()).resolves.toBe("fake-token");
    expect(sdk.initializeAppCheck).toHaveBeenCalledTimes(1);
  });

  it("SEC-10 the Firebase app gets the build's api key and project id, and no other secret", async () => {
    const { createAppCheckTokenGetter } = await load();
    await createAppCheckTokenGetter({ hostname: DEPLOYED })();
    const [options] = sdk.initializeApp.mock.calls[0] as [Record<string, unknown>];
    expect(options.apiKey).toBe("test-web-api-key");
    expect(options.projectId).toBe("demo-tilo-web");
    expect(Object.keys(options).sort()).toEqual(["apiKey", "appId", "projectId"]);
  });

  it("SEC-10 a token request that never answers resolves null after TOKEN_TIMEOUT_MS", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    sdk.getToken.mockImplementation(() => new Promise<never>(() => undefined));
    const { createAppCheckTokenGetter, TOKEN_TIMEOUT_MS } = await load();
    expect(TOKEN_TIMEOUT_MS).toBeGreaterThanOrEqual(1000);
    expect(TOKEN_TIMEOUT_MS).toBeLessThanOrEqual(10_000);
    let answer: string | null | undefined;
    void createAppCheckTokenGetter({ hostname: DEPLOYED })().then((t) => {
      answer = t;
    });
    await vi.waitFor(() => expect(sdk.getToken).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(TOKEN_TIMEOUT_MS - 1000);
    expect(answer).toBeUndefined(); // still waiting inside the bound
    await vi.advanceTimersByTimeAsync(1100);
    expect(answer).toBeNull();
  });

  it("SEC-10 a quick token leaves no pending timer behind", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { createAppCheckTokenGetter } = await load();
    const answer = createAppCheckTokenGetter({ hostname: DEPLOYED })();
    await vi.waitFor(() => expect(sdk.getToken).toHaveBeenCalled());
    await expect(answer).resolves.toBe("fake-token");
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("SEC-10 a hung or failed SDK does not cost every request", () => {
  const FAKE: { toFake: ("setTimeout" | "clearTimeout" | "Date")[] } = {
    toFake: ["setTimeout", "clearTimeout", "Date"],
  };

  it("SEC-10 after a deadline the getter answers null at once for BACKOFF_MS, then asks again", async () => {
    vi.useFakeTimers(FAKE);
    sdk.getToken.mockImplementation(() => new Promise<never>(() => undefined));
    const { createAppCheckTokenGetter, TOKEN_TIMEOUT_MS, BACKOFF_MS } = await load();
    const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });

    const first = getter();
    await vi.waitFor(() => expect(sdk.getToken).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(TOKEN_TIMEOUT_MS + 1);
    await expect(first).resolves.toBeNull();

    await expect(getter()).resolves.toBeNull(); // paused: no wait, no new SDK call
    await expect(getter()).resolves.toBeNull();
    expect(sdk.getToken).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    await vi.advanceTimersByTimeAsync(BACKOFF_MS);
    sdk.getToken.mockImplementation(async () => ({ token: "fake-token" }));
    await expect(getter()).resolves.toBe("fake-token");
  });

  it("SEC-10 a dynamic import that failed is retried after the pause, not cached as null for the page's life", async () => {
    vi.useFakeTimers(FAKE);
    vi.doMock("firebase/app-check", () => {
      throw new Error("chunk failed to load");
    });
    try {
      const { createAppCheckTokenGetter, BACKOFF_MS } = await load();
      const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });
      await expect(getter()).resolves.toBeNull();
      expect(sdk.initializeAppCheck).not.toHaveBeenCalled();

      vi.doMock("firebase/app-check", workingAppCheck); // the network is back
      await expect(getter()).resolves.toBeNull(); // still inside the pause
      await vi.advanceTimersByTimeAsync(BACKOFF_MS + 1);
      await expect(getter()).resolves.toBe("fake-token");
      expect(sdk.initializeAppCheck).toHaveBeenCalledTimes(1);
    } finally {
      vi.doMock("firebase/app-check", workingAppCheck);
    }
  });

  it("SEC-10 an SDK that refuses to start is not retried", async () => {
    vi.useFakeTimers(FAKE);
    sdk.initializeAppCheck.mockImplementationOnce(() => {
      throw new Error("appCheck/already-initialized");
    });
    const { createAppCheckTokenGetter, BACKOFF_MS } = await load();
    const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });
    await expect(getter()).resolves.toBeNull();
    await vi.advanceTimersByTimeAsync(BACKOFF_MS + 1);
    await expect(getter()).resolves.toBeNull();
    expect(sdk.initializeAppCheck).toHaveBeenCalledTimes(1);
  });
});
