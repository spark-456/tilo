// SEC-10 (PRD 16 "Rate limits, App Check and spend caps"; PRD 6.2 "Firebase Authentication, App Check"):
// the web client starts Firebase App Check and hands the API client a token getter.
//
// Public interface pinned here (apps/web/src/appcheck/appCheck.ts):
//   createAppCheckTokenGetter({ hostname }: { hostname: string }): () => Promise<string | null>
// - On a deployed host it calls firebase/app `initializeApp` with the tilo-web appId (config.ts), then
//   firebase/app-check `initializeAppCheck(app, { provider: new ReCaptchaEnterpriseProvider(siteKey),
//   isTokenAutoRefreshEnabled: true })` and answers with the token from `getToken`.
// - On a local host (localhost, 127.0.0.1, [::1], *.localhost) it must not start reCAPTCHA or reach Google:
//   dev, tests and the emulators make no external call (EFF-01). Whether it answers null or a debug string is
//   open; it must never call fetch, never build a ReCaptchaEnterpriseProvider.
// - It never throws and the getter never rejects: no token is `null` (the API only logs a missing token
//   while enforcement is off).
// The host decides, not `import.meta.env.DEV` (Vitest is DEV, and these tests need the deployed path).
//
// The Firebase SDK is replaced by a fake below, so nothing here touches the network or needs the package.
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FIREBASE_APP_ID, RECAPTCHA_SITE_KEY } from "./config";

const sdk = vi.hoisted(() => {
  class ReCaptchaEnterpriseProvider {
    constructor(readonly siteKey: string) {
      sdk.providers.push(siteKey);
    }
  }
  class CustomProvider {
    constructor(readonly options: unknown) {}
  }
  class ReCaptchaV3Provider {
    constructor(readonly siteKey: string) {
      sdk.providers.push(`v3:${siteKey}`);
    }
  }
  const sdk = {
    providers: [] as string[],
    ReCaptchaEnterpriseProvider,
    CustomProvider,
    ReCaptchaV3Provider,
    initializeApp: vi.fn((options: unknown) => ({ name: "[DEFAULT]", options })),
    getApps: vi.fn(() => [] as unknown[]),
    getApp: vi.fn(() => ({ name: "[DEFAULT]", options: {} })),
    initializeAppCheck: vi.fn((_app: unknown, _options: unknown) => ({ appCheck: true })),
    getToken: vi.fn(async (_appCheck: unknown, _forceRefresh?: boolean) => ({
      token: "fake-app-check-token",
    })),
    onTokenChanged: vi.fn(() => () => undefined),
    setTokenAutoRefreshEnabled: vi.fn(),
  };
  return sdk;
});

vi.mock("firebase/app", () => ({
  initializeApp: sdk.initializeApp,
  getApps: sdk.getApps,
  getApp: sdk.getApp,
}));
vi.mock("firebase/app-check", () => ({
  initializeAppCheck: sdk.initializeAppCheck,
  getToken: sdk.getToken,
  onTokenChanged: sdk.onTokenChanged,
  setTokenAutoRefreshEnabled: sdk.setTokenAutoRefreshEnabled,
  ReCaptchaEnterpriseProvider: sdk.ReCaptchaEnterpriseProvider,
  ReCaptchaV3Provider: sdk.ReCaptchaV3Provider,
  CustomProvider: sdk.CustomProvider,
}));

const DEPLOYED = "example-project.web.app";
const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "app.localhost"];

async function load() {
  vi.resetModules();
  return (await import("./appCheck")) as {
    createAppCheckTokenGetter(env: { hostname: string }): () => Promise<string | null>;
  };
}

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sdk.providers.length = 0;
  for (const fn of [
    sdk.initializeApp,
    sdk.getApps,
    sdk.getApp,
    sdk.initializeAppCheck,
    sdk.getToken,
    sdk.onTokenChanged,
    sdk.setTokenAutoRefreshEnabled,
  ])
    fn.mockClear();
  sdk.getToken.mockImplementation(async () => ({ token: "fake-app-check-token" }));
  sdk.initializeAppCheck.mockImplementation(() => ({ appCheck: true }));
  fetchSpy = vi.fn(async () => {
    throw new Error("SEC-10: App Check setup must not call fetch");
  });
  vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SEC-10 a deployed host starts App Check with reCAPTCHA Enterprise", () => {
  it("SEC-10 App Check starts with ReCaptchaEnterpriseProvider(site key) and token auto-refresh on", async () => {
    const { createAppCheckTokenGetter } = await load();
    const getToken = createAppCheckTokenGetter({ hostname: DEPLOYED });
    await getToken(); // starting may be eager or on the first token request

    expect(sdk.initializeAppCheck).toHaveBeenCalledTimes(1);
    const [, options] = sdk.initializeAppCheck.mock.calls[0] as [
      unknown,
      { provider: unknown; isTokenAutoRefreshEnabled?: boolean },
    ];
    expect(options.provider).toBeInstanceOf(sdk.ReCaptchaEnterpriseProvider);
    expect((options.provider as { siteKey: string }).siteKey).toBe(RECAPTCHA_SITE_KEY);
    expect(options.isTokenAutoRefreshEnabled).toBe(true);
    expect(sdk.providers).toEqual([RECAPTCHA_SITE_KEY]); // the score-based Enterprise key, not v3
  });

  it("SEC-10 the Firebase app is initialised with the tilo-web appId and App Check is given that app", async () => {
    const { createAppCheckTokenGetter } = await load();
    await createAppCheckTokenGetter({ hostname: DEPLOYED })();

    expect(sdk.initializeApp).toHaveBeenCalledTimes(1);
    const [config] = sdk.initializeApp.mock.calls[0] as [Record<string, unknown>];
    expect(config.appId).toBe(FIREBASE_APP_ID);
    const initialised = sdk.initializeApp.mock.results[0]?.value;
    expect(sdk.initializeAppCheck.mock.calls[0]?.[0]).toBe(initialised);
  });

  it("SEC-10 the getter answers with the token the SDK gives, asked of the App Check instance", async () => {
    const { createAppCheckTokenGetter } = await load();
    const getter = createAppCheckTokenGetter({ hostname: DEPLOYED });

    await expect(getter()).resolves.toBe("fake-app-check-token");
    const instance = sdk.initializeAppCheck.mock.results[0]?.value;
    expect(sdk.getToken.mock.calls[0]?.[0]).toBe(instance);
    // The SDK caches and auto-refreshes; the client never forces a refresh on every request.
    expect(sdk.getToken.mock.calls[0]?.[1] ?? false).toBe(false);
  });

  it("SEC-10 asking twice, or building the getter twice, starts App Check once", async () => {
    const { createAppCheckTokenGetter } = await load();
    const first = createAppCheckTokenGetter({ hostname: DEPLOYED });
    const second = createAppCheckTokenGetter({ hostname: DEPLOYED });
    await first();
    await first();
    await second();

    expect(sdk.initializeAppCheck).toHaveBeenCalledTimes(1); // a second start throws in the SDK
    expect(sdk.initializeApp.mock.calls.length).toBeLessThanOrEqual(1);
  });

  it("SEC-10 a failing token request resolves to null and never throws", async () => {
    sdk.getToken.mockImplementation(async () => {
      throw new Error("appCheck/recaptcha-error");
    });
    const { createAppCheckTokenGetter } = await load();
    await expect(createAppCheckTokenGetter({ hostname: DEPLOYED })()).resolves.toBeNull();
  });

  it("SEC-10 an SDK that cannot start resolves the getter to null and does not throw when building it", async () => {
    sdk.initializeAppCheck.mockImplementation(() => {
      throw new Error("appCheck/already-initialized");
    });
    // The real SDK throws when asked for a token of an App Check that never started.
    sdk.getToken.mockImplementation(async (appCheck: unknown) => {
      if (typeof appCheck !== "object" || appCheck === null) throw new Error("appCheck/invalid");
      return { token: "fake-app-check-token" };
    });
    const { createAppCheckTokenGetter } = await load();
    let getter: (() => Promise<string | null>) | undefined;
    expect(() => {
      getter = createAppCheckTokenGetter({ hostname: DEPLOYED });
    }).not.toThrow();
    await expect(getter?.()).resolves.toBeNull();
  });

  it("SEC-10 a token that is not a non-empty string is treated as no token", async () => {
    const { createAppCheckTokenGetter } = await load();
    for (const bad of [{ token: "" }, { token: undefined }, {}, null, undefined]) {
      sdk.getToken.mockImplementation(async () => bad as { token: string });
      await expect(createAppCheckTokenGetter({ hostname: DEPLOYED })()).resolves.toBeNull();
    }
  });
});

describe("SEC-10 a local host makes no reCAPTCHA or Google call (EFF-01)", () => {
  it("SEC-10 on localhost and the loopback hosts there is no reCAPTCHA provider and no fetch", async () => {
    for (const hostname of LOCAL_HOSTS) {
      sdk.providers.length = 0;
      sdk.initializeAppCheck.mockClear();
      const { createAppCheckTokenGetter } = await load();
      const getter = createAppCheckTokenGetter({ hostname });
      const token = await getter();

      expect(sdk.providers, hostname).toEqual([]);
      for (const call of sdk.initializeAppCheck.mock.calls) {
        const provider = (call[1] as { provider: unknown }).provider;
        expect(provider, hostname).not.toBeInstanceOf(sdk.ReCaptchaEnterpriseProvider);
        expect(provider, hostname).not.toBeInstanceOf(sdk.ReCaptchaV3Provider);
      }
      expect(token === null || typeof token === "string", hostname).toBe(true);
      expect(fetchSpy, hostname).not.toHaveBeenCalled();
    }
  });

  it("SEC-10 a host that only contains the word localhost is not local", async () => {
    for (const hostname of [
      "localhost.example.com",
      "notlocalhost.web.app",
      "127.0.0.1.example.com",
      "example.com/localhost",
    ]) {
      sdk.providers.length = 0;
      const { createAppCheckTokenGetter } = await load();
      await createAppCheckTokenGetter({ hostname })();
      expect(sdk.providers, hostname).toEqual([RECAPTCHA_SITE_KEY]);
    }
  });
});

describe("SEC-10 properties", () => {
  const remote = fc
    .domain()
    .filter((d) => d !== "localhost" && !d.endsWith(".localhost") && !/^[\d.]+$/.test(d));

  it("SEC-10 property: any non-local host starts the Enterprise provider with exactly the one site key", async () => {
    await fc.assert(
      fc.asyncProperty(remote, async (hostname) => {
        sdk.providers.length = 0;
        const { createAppCheckTokenGetter } = await load();
        await createAppCheckTokenGetter({ hostname })();
        expect(sdk.providers).toEqual([RECAPTCHA_SITE_KEY]);
      }),
      { numRuns: 25 },
    );
  });

  it("SEC-10 property: the getter never rejects, whatever the SDK does", async () => {
    const behaviours = fc.constantFrom("token", "empty", "reject", "throw-sync", "garbage");
    await fc.assert(
      fc.asyncProperty(remote, behaviours, async (hostname, behaviour) => {
        sdk.getToken.mockImplementation((async () => {
          if (behaviour === "reject") throw new Error("boom");
          if (behaviour === "throw-sync") throw new TypeError("sync boom");
          if (behaviour === "empty") return { token: "" };
          if (behaviour === "garbage") return 42;
          return { token: "fake-app-check-token" };
        }) as typeof sdk.getToken);
        const { createAppCheckTokenGetter } = await load();
        const token = await createAppCheckTokenGetter({ hostname })();
        expect(token === null || (typeof token === "string" && token.length > 0)).toBe(true);
        if (behaviour !== "token") expect(token).toBeNull();
      }),
      { numRuns: 25 },
    );
  });
});
