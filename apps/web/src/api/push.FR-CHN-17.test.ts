// FR-CHN-17d: the web push flow, with a fake browser and a fake tilo-api. Nothing here asks a real browser for
// permission, registers a worker or makes a request.
import fs from "node:fs";
import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { type PushEnv, type PushSub, WORKER_PATH, createPushFlow } from "./push";

const KEY = `B${"x".repeat(86)}`;
const ENDPOINT = `https://fcm.googleapis.com/fcm/send/${"a".repeat(40)}`;
const KEYS = { p256dh: "p".repeat(87), auth: "a".repeat(22) };

function rig(
  over: {
    permission?: NotificationPermission;
    supported?: boolean;
    publicKey?: string | null;
  } = {},
) {
  const calls: string[] = [];
  let sub: PushSub | null = null;
  let stored = 0;
  let permission: NotificationPermission = over.permission ?? "default";
  const body = (delivery = "off_until_owner_policy") => ({
    devices: stored,
    delivery,
    public_key: over.publicKey === undefined ? KEY : over.publicKey,
  });
  const http = {
    getJson: async (path: string) => {
      calls.push(`GET ${path}`);
      return body();
    },
    postJson: async (path: string, payload: unknown) => {
      calls.push(`POST ${path} ${JSON.stringify(payload)}`);
      stored = path.endsWith("subscribe") && !path.endsWith("unsubscribe") ? 1 : 0;
      return body();
    },
  };
  const env: PushEnv = {
    supported: over.supported ?? true,
    permission: () => permission,
    request: async () => {
      calls.push("request");
      permission = over.permission === "denied" ? "denied" : "granted";
      return permission;
    },
    registration: async () => {
      calls.push(`register ${WORKER_PATH}`);
      return {
        pushManager: {
          getSubscription: async () => sub,
          subscribe: async (o) => {
            calls.push(
              `subscribe visible=${o.userVisibleOnly} key=${(o.applicationServerKey as Uint8Array).length}`,
            );
            sub = {
              toJSON: () => ({ endpoint: ENDPOINT, keys: KEYS }),
              unsubscribe: async () => {
                calls.push("unsubscribe local");
                sub = null;
                return true;
              },
            };
            return sub;
          },
        },
      };
    },
  };
  return { flow: createPushFlow(http, env), calls };
}

describe("FR-CHN-17d the push flow", () => {
  it("FR-CHN-17 asks nothing until enable, then permission, worker, subscription, tilo-api, in that order", async () => {
    const { flow, calls } = rig();
    expect((await flow.read()).here).toBe(false);
    expect(calls).toEqual(["GET /v1/push"]); // reading never asks permission or registers
    const result = await flow.enable();
    expect(result).toEqual({
      ok: true,
      state: { devices: 1, delivery: "off_until_owner_policy" },
    });
    expect(calls.slice(1)).toEqual([
      "GET /v1/push",
      "request",
      `register ${WORKER_PATH}`,
      "subscribe visible=true key=65",
      `POST /v1/push/subscribe ${JSON.stringify({ endpoint: ENDPOINT, keys: KEYS })}`,
    ]);
    expect((await flow.read()).here).toBe(true);
  });

  it("FR-CHN-17 turns off by removing it from tilo-api and from this browser", async () => {
    const { flow, calls } = rig();
    await flow.enable();
    calls.length = 0;
    expect(await flow.disable()).toEqual({
      ok: true,
      state: { devices: 0, delivery: "off_until_owner_policy" },
    });
    expect(calls).toEqual([
      `register ${WORKER_PATH}`,
      `POST /v1/push/unsubscribe ${JSON.stringify({ endpoint: ENDPOINT })}`,
      "unsubscribe local",
    ]);
  });

  it("FR-CHN-17 says why it did not turn on and leaves nothing half made", async () => {
    expect(await rig({ supported: false }).flow.enable()).toEqual({
      ok: false,
      problem: "unsupported",
    });
    const none = rig({ publicKey: null });
    expect(await none.flow.enable()).toEqual({ ok: false, problem: "not_configured" });
    expect(none.calls).toEqual(["GET /v1/push"]); // no permission prompt for a deployment that cannot send
    const denied = rig({ permission: "denied" });
    expect(await denied.flow.enable()).toEqual({ ok: false, problem: "denied" });
    expect(denied.calls.some((c) => c.startsWith("subscribe") || c.startsWith("POST"))).toBe(false);
  });

  it("FR-CHN-17 release removes this browser's subscription and leaves the policy alone", async () => {
    const { flow, calls } = rig();
    await flow.enable();
    calls.length = 0;
    await flow.release();
    expect(calls).toEqual([
      `register ${WORKER_PATH}`,
      `POST /v1/push/unsubscribe ${JSON.stringify({ endpoint: ENDPOINT })}`,
      "unsubscribe local",
    ]);
    await expect(rig({ supported: false }).flow.release()).resolves.toBeUndefined(); // never throws
  });
});

// The worker runs here in a bare vm with a fake `self`: what it shows, and where a tap may go.
function worker() {
  const src = fs.readFileSync(new URL("../../public/push-sw.js", import.meta.url), "utf-8");
  const shown: { title: string; options: Record<string, unknown> }[] = [];
  const opened: string[] = [];
  const handlers: Record<string, (e: unknown) => void> = {};
  const self = {
    addEventListener: (name: string, fn: (e: unknown) => void) => {
      handlers[name] = fn;
    },
    registration: {
      showNotification: async (title: string, options: Record<string, unknown>) => {
        shown.push({ title, options });
      },
    },
    clients: {
      openWindow: async (path: string) => {
        opened.push(path);
      },
    },
  };
  vm.runInNewContext(src, { self });
  const push = (payload: unknown, raw?: string) =>
    handlers.push?.({
      data: { json: () => (raw === undefined ? payload : JSON.parse(raw)) },
      waitUntil: () => undefined,
    });
  const click = (data: unknown) =>
    handlers.notificationclick?.({
      notification: { close: () => undefined, data },
      waitUntil: () => undefined,
    });
  return { src, shown, opened, push, click };
}

describe("FR-CHN-17d the service worker", () => {
  it("FR-CHN-17 shows plain bounded text only, with no actions, and ignores a payload of the wrong shape", () => {
    const w = worker();
    w.push({
      title: "T".repeat(500),
      body: "B".repeat(900),
      tag: "card_1",
      path: "/park/home?card=card_1",
    });
    expect(w.shown).toHaveLength(1);
    const first = w.shown[0] as { title: string; options: Record<string, unknown> };
    expect(first.title).toHaveLength(80);
    expect(Object.keys(first.options).sort()).toEqual(["body", "data", "tag"]); // no actions, icon, image, vibrate
    expect((first.options.body as string).length).toBe(200);
    for (const bad of [null, "text", 7, [1], {}, { title: 5 }, { title: "   " }, { body: "x" }]) {
      w.push(bad);
    }
    w.push(undefined, "not json {");
    expect(w.shown).toHaveLength(1); // none of them showed anything
  });

  it("FR-CHN-17 a tap opens only an allowlisted same-origin relative path, else the Needs-you page", () => {
    const w = worker();
    w.click({ path: "/park/home?card=card_1" });
    for (const bad of [
      "https://evil.example/x",
      "//evil.example/x",
      "/park/home?card=../x",
      "/park/world/w_1",
      "javascript:alert(1)",
      "/park/home?card=x&redirect=https://evil.example",
      42,
      null,
    ]) {
      w.click({ path: bad });
    }
    w.click(undefined);
    expect(w.opened[0]).toBe("/park/home?card=card_1");
    expect(w.opened.slice(1).every((p) => p === "/park/home")).toBe(true);
  });

  it("FR-CHN-17 fetches and imports nothing, caches nothing and holds no address of its own", () => {
    const { src } = worker();
    expect(src).not.toMatch(
      /\bfetch\(|importScripts|XMLHttpRequest|caches\.|indexedDB|https?:\/\//,
    );
    expect(src).not.toMatch(/\bactions\b|\bicon\b|\bimage\b/);
  });
});
