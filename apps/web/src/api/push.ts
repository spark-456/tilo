// FR-CHN-17d (PRD 11, 16): the web half of browser notifications, framework-free. `enable` runs only from the
// person's own click: it asks tilo-api for the deployment's public key (`GET /v1/push`), asks the browser's permission,
// registers the service worker, subscribes this browser and posts the subscription to tilo-api, which stores it for
// the signed-in person. The subscription (a capability URL and its keys) is never stored here, shown or logged.
// `enable` is called only after the control has shown the consent line and the owner confirmed: it then also
// asks tilo-api for the owner's standing push policy (`POST /v1/push/policy`, confirm true), and `disable` ends it.
// `delivery` is tilo-api's word: `off_until_owner_policy` means nothing is sent yet, and the page says so.
export type PushDelivery = "ready" | "off_until_owner_policy";
export type PushProblem = "unsupported" | "not_configured" | "denied" | "failed";
export interface PushState {
  devices: number;
  delivery: PushDelivery;
}
export type PushResult = { ok: true; state: PushState } | { ok: false; problem: PushProblem };

export interface PushView {
  here: boolean;
  permission: NotificationPermission | "unsupported";
  state: PushState | null;
}

export interface PushFlow {
  read(): Promise<PushView>;
  enable(): Promise<PushResult>;
  disable(): Promise<PushResult>;
}

interface Http {
  getJson(path: string): Promise<unknown>;
  postJson(path: string, body: unknown): Promise<unknown>;
}

/** What the browser gives, as far as this flow needs it (a test passes a fake). */
export interface PushEnv {
  supported: boolean;
  permission(): NotificationPermission;
  request(): Promise<NotificationPermission>;
  registration(): Promise<PushRegistration>;
}
export interface PushRegistration {
  pushManager: {
    getSubscription(): Promise<PushSub | null>;
    subscribe(options: {
      userVisibleOnly: boolean;
      applicationServerKey: BufferSource;
    }): Promise<PushSub>;
  };
}
export interface PushSub {
  toJSON(): { endpoint?: string; keys?: Record<string, string> };
  unsubscribe(): Promise<boolean>;
}

export const WORKER_PATH = "/push-sw.js";
const KEY_SHAPE = /^[A-Za-z0-9_-]{80,100}$/;
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

export function browserEnv(): PushEnv {
  const ok =
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window;
  return {
    supported: ok,
    permission: () => (ok ? Notification.permission : "denied"),
    request: () => Notification.requestPermission(),
    registration: () => navigator.serviceWorker.register(WORKER_PATH),
  };
}

function decodeKey(key: string): Uint8Array<ArrayBuffer> {
  const raw = atob(key.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function stateOf(body: unknown): { state: PushState; publicKey: string | null } | null {
  if (!isObject(body) || typeof body.devices !== "number") return null;
  if (body.delivery !== "ready" && body.delivery !== "off_until_owner_policy") return null;
  const key =
    typeof body.public_key === "string" && KEY_SHAPE.test(body.public_key) ? body.public_key : null;
  return { state: { devices: body.devices, delivery: body.delivery }, publicKey: key };
}

export function createPushFlow(http: Http, env: PushEnv = browserEnv()): PushFlow {
  const fail = (problem: PushProblem): PushResult => ({ ok: false, problem });
  const turn = async (on: boolean) =>
    stateOf(await http.postJson("/v1/push/policy", on ? { on, confirm: true } : { on }));
  return {
    async read() {
      const permission = env.supported ? env.permission() : "unsupported";
      let here = false;
      if (env.supported && permission === "granted") {
        try {
          here = (await (await env.registration()).pushManager.getSubscription()) !== null;
        } catch {
          here = false;
        }
      }
      try {
        return { here, permission, state: stateOf(await http.getJson("/v1/push"))?.state ?? null };
      } catch {
        return { here, permission, state: null };
      }
    },
    async enable() {
      if (!env.supported) return fail("unsupported");
      let known: ReturnType<typeof stateOf>;
      try {
        known = stateOf(await http.getJson("/v1/push"));
      } catch {
        return fail("failed");
      }
      if (known === null) return fail("failed");
      if (known.publicKey === null) return fail("not_configured");
      if ((await env.request()) !== "granted") return fail("denied");
      let sub: PushSub | null = null;
      try {
        const { pushManager } = await env.registration();
        sub =
          (await pushManager.getSubscription()) ??
          (await pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: decodeKey(known.publicKey),
          }));
        const { endpoint, keys } = sub.toJSON();
        const saved = stateOf(await http.postJson("/v1/push/subscribe", { endpoint, keys }));
        if (saved === null) throw new Error("answer");
        const policy = await turn(true).catch(() => null); // a member is refused: the device stays, delivery off
        return { ok: true, state: (policy ?? saved).state };
      } catch {
        await sub?.unsubscribe().catch(() => false); // nothing was saved: leave no half-made subscription
        return fail("failed");
      }
    },
    async disable() {
      try {
        const sub = await (await env.registration()).pushManager.getSubscription();
        const endpoint = sub?.toJSON().endpoint;
        const answer = stateOf(
          endpoint
            ? await http.postJson("/v1/push/unsubscribe", { endpoint })
            : await http.getJson("/v1/push"), // this browser holds none: nothing to remove
        );
        if (answer === null) throw new Error("answer");
        await sub?.unsubscribe();
        const ended = await turn(false).catch(() => null);
        return { ok: true, state: (ended ?? answer).state };
      } catch {
        return fail("failed");
      }
    },
  };
}
