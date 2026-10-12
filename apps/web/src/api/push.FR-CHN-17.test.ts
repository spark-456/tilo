// FR-CHN-17d: the web push flow, with a fake browser and a fake tilo-api. Nothing here asks a real browser for
// permission, registers a worker or makes a request.
import fs from "node:fs";
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

  it("FR-CHN-17 the service worker only shows a bounded title and body and opens the app root", () => {
    const src = fs.readFileSync(new URL("../../public/push-sw.js", import.meta.url), "utf-8");
    expect(src).toMatch(/addEventListener\("push"/);
    expect(src).toMatch(/addEventListener\("notificationclick"/);
    expect(src).not.toMatch(/\bfetch\(|importScripts|XMLHttpRequest|https?:\/\//);
    expect(src).toMatch(/slice\(0, max\)/);
    expect(src).toMatch(/openWindow\("\/"\)/);
  });
});
