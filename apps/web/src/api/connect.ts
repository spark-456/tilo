// ADR-0035 L4 (LC-01 to LC-06; FR-CON-02): the web half of the Google connect flow, framework-free.
// `start` asks tilo-api for Google's sign-in link and saves the link's `state` in sessionStorage before the page opens it;
// `finish` is the callback page's one step: it posts only when the returned `state` equals the saved one, clears the saved
// value, and turns the answer into a plain result. The one-time `code` goes from the address bar (already stripped by
// `oauth/capture.ts`) to one POST and is never stored, logged or shown. Nothing here loads a third-party asset.
import { TiloApiError } from "./http";

/** The callback address Google redirects the browser to (LC-01); Firebase Hosting serves the SPA there. */
export const CALLBACK_PATH = "/oauth/google/callback";
const STATE_KEY = "tilo.google.connect.state";

/** The three connectors of one Google sign-in (CON-D10): disconnecting any one ends all three (LC-06). */
export const GOOGLE_PERSON_CONNECTORS = ["gmail", "google_drive", "google_calendar"] as const;

const STATE_SHAPE = /^[A-Za-z0-9_-]{16,128}$/;
const AUTHORIZE_HOST = "accounts.google.com";

export type ConnectionState = "connected" | "attention" | "available";
export interface ConnectionRow {
  id: string;
  name: string;
  state: ConnectionState;
}

export type StartResult =
  | { kind: "redirect"; url: string }
  | { kind: "nothing_missing" }
  | { kind: "failed" };

export type FinishResult =
  | { kind: "connected"; lines: string[] }
  | { kind: "not_granted" }
  | { kind: "wrong_account" }
  | { kind: "start_again" }
  | { kind: "unavailable" };

export interface CallbackParams {
  state: string;
  code?: string;
  error?: string;
}

export interface ConnectFlow {
  /** The person's three Google connectors and where each stands (`GET /v1/connectors`). */
  list(): Promise<ConnectionRow[]>;
  /** Asks for the link and saves its state; the caller opens `url`. */
  start(connector: string, capabilities: readonly string[]): Promise<StartResult>;
  /** The callback page's step (see the header). */
  finish(params: CallbackParams): Promise<FinishResult>;
  /** Leaves for Google's sign-in (the one place the address changes; pages never touch the location). */
  open(url: string): void;
  /** True when tilo-api confirmed the disconnect. */
  disconnect(connector: string): Promise<boolean>;
}

interface Http {
  getJson(path: string): Promise<unknown>;
  postJson(path: string, body: unknown): Promise<unknown>;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

function defaultStore(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null; // blocked storage: the flow cannot start (it could not be checked on the way back)
  }
}

/** The `state` of Google's link, only when the link is the real authorisation endpoint and the state is well formed. */
export function stateOf(link: string): string | null {
  try {
    const url = new URL(link);
    const state = url.searchParams.get("state");
    if (url.protocol !== "https:" || url.hostname !== AUTHORIZE_HOST) return null;
    return state !== null && STATE_SHAPE.test(state) ? state : null;
  } catch {
    return null;
  }
}

const readState = (store: Storage | null): string | null => {
  try {
    return store?.getItem(STATE_KEY) ?? null;
  } catch {
    return null;
  }
};
const clearState = (store: Storage | null): void => {
  try {
    store?.removeItem(STATE_KEY);
  } catch {
    // nothing to clear
  }
};

export function createConnectFlow(
  http: Http,
  store: () => Storage | null = defaultStore,
  navigate: (url: string) => void = (url) => window.location.assign(url),
): ConnectFlow {
  return {
    open: navigate,
    async list() {
      const body = await http.getJson("/v1/connectors");
      const rows = isObject(body) && Array.isArray(body.connectors) ? body.connectors : [];
      const out: ConnectionRow[] = [];
      for (const id of GOOGLE_PERSON_CONNECTORS) {
        const row = rows.find((r) => isObject(r) && r.id === id) as
          | Record<string, unknown>
          | undefined;
        if (!row || typeof row.name !== "string") continue;
        const state =
          row.state === "connected" || row.state === "attention" ? row.state : "available";
        out.push({ id, name: row.name, state });
      }
      return out;
    },

    async start(connector, capabilities) {
      const saved = store();
      if (!saved) return { kind: "failed" };
      let body: unknown;
      try {
        body = await http.postJson("/v1/connectors/connect", { connector, capabilities });
      } catch {
        return { kind: "failed" };
      }
      if (!isObject(body) || !("authorize_url" in body)) return { kind: "failed" };
      if (body.authorize_url === null) return { kind: "nothing_missing" };
      const url = body.authorize_url;
      const state = typeof url === "string" ? stateOf(url) : null;
      if (typeof url !== "string" || state === null) return { kind: "failed" };
      try {
        saved.setItem(STATE_KEY, state);
      } catch {
        return { kind: "failed" };
      }
      return { kind: "redirect", url };
    },

    async finish(params) {
      const saved = store();
      const expected = readState(saved);
      // Nothing is posted unless the returned state is the one this tab saved (LC-02).
      if (expected === null || expected !== params.state) return { kind: "start_again" };
      clearState(saved);
      const hasCode = typeof params.code === "string" && params.code !== "";
      const body = hasCode
        ? { state: params.state, code: params.code }
        : { state: params.state, error: params.error ?? "access_denied" };
      try {
        const got = await http.postJson("/v1/connectors/callback", body);
        const lines =
          isObject(got) && Array.isArray(got.scope_lines)
            ? got.scope_lines.filter((l): l is string => typeof l === "string")
            : [];
        return lines.length > 0 ? { kind: "connected", lines } : { kind: "unavailable" };
      } catch (e) {
        if (e instanceof TiloApiError && e.status === 400) {
          if (e.refusal === "not_granted" || e.refusal === "wrong_account") {
            return { kind: e.refusal };
          }
          return { kind: "start_again" };
        }
        return { kind: "unavailable" };
      }
    },

    async disconnect(connector) {
      try {
        const got = await http.postJson("/v1/connectors/disconnect", { connector });
        return isObject(got) && got.disconnected === true;
      } catch {
        return false;
      }
    },
  };
}

/** The plain sentence for each result (no codes, no Google text). */
export const RESULT_TEXT: Record<FinishResult["kind"], string> = {
  connected: "Google is connected.",
  not_granted: "Consent was not granted, so nothing was connected.",
  wrong_account: "That was not the account Tilo expected. Nothing was connected.",
  start_again: "That sign-in could not be completed. Please start again from Connectors.",
  unavailable: "Tilo could not finish connecting right now. Please start again from Connectors.",
};
