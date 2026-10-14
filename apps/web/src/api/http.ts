// CL-INT-3: the HTTP TiloClient over the services/api routes (API_CL_INT_1.md, API_CL_INT_2.md).
// Request and response shapes are the contract types re-exported by ./client; nothing here
// restates a contract. Sign-in (SEC-15): the app's own getter supplies the Firebase ID token, sent as a Bearer
// header only (never a cookie, URL or body); the API's own principal dependency decides.
import type { Brief, Card, Event, Layout } from "@tilo/contracts";
import type {
  ApproachesResult,
  ApprovalRequest,
  CardAnswer,
  DeliveryResult,
  IntakeResult,
  QuestionAnswer,
  TiloClient,
} from "./client";
import { API_DETAIL_MESSAGES } from "./errorCodes";
import { type FieldSpec, type FieldsApi, fieldSpecsOf } from "./fields";
import { type ItemApi, type PinnedItem, pinnedItemOf } from "./item";
import { type HostStarted, isHostStarted, refusalOf } from "./meetingHost";
import { bootstrapPerson } from "./peopleBootstrap";
import {
  type ScheduleRequest,
  type ScheduleView,
  type SchedulesApi,
  isScheduleView,
} from "./schedules";
import { type StopResult, isStopResult } from "./stop";

/** What a person reads when a call fails (PRD 18.4). `retryable` is true for 5xx and for network
 * or unreadable-reply failures; a 4xx carries a reason and retrying the same call will not help. */
export class TiloApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly retryable: boolean,
    /** The call changes something on the server: a retryable failure may still have happened there. */
    readonly write = false,
    /** The server's stable refusal code (SEC-15: `under_construction`, `declaration_required`), or null. */
    readonly code: string | null = null,
    /** NFR-22 / NFR-24: a 503 that said `replay_only: true` (live models unavailable); finished runs can still be replayed. */
    readonly replayOnly = false,
    /** The refusal's short word (a connector rule such as `MH-02`, or a reason such as `already_hosted`), or null. */
    readonly refusal: string | null = null,
  ) {
    super(message);
    this.name = "TiloApiError";
  }
}

const UNREACHABLE = "Tilo could not be reached. Check your connection and try again.";
const SERVER_TROUBLE = "Tilo had a problem on its side.";
/** NFR-22: the web's own sentence for a replay-only 503; the server's free text is never shown. */
const REPLAY_ONLY =
  "Live models are unavailable right now, so nothing new was started. Finished runs can still be replayed.";
const SAFETY_UNAVAILABLE = "The safety screen is unavailable. Try again later.";
const NOT_CONFIGURED = "This feature is not configured on this server.";
/** Legacy routes use these exact details instead of a code. Match only known wire values;
 * no server text, including extensions of these sentences, is ever displayed. */
const SAFETY_DETAILS = new Set([
  "The safety screen is unavailable; nothing was stored.",
  "The safety screen is unavailable; nothing was answered.",
  "The safety screen is unavailable; nothing changed.",
]);

/** The two 502 sentences tilo-api writes for the Director (services/api intake.py, tasks.py). */
const DIRECTOR_DETAILS = new Set([
  "The Director could not draft a brief.",
  "The Director could not propose approaches.",
]);

function unavailableMessage(text: string): string {
  try {
    const body = JSON.parse(text) as { code?: unknown; detail?: unknown } | null;
    if (body?.code === "not_configured" || body?.detail === "not_configured") {
      return NOT_CONFIGURED;
    }
    if (typeof body?.detail === "string" && Object.hasOwn(API_DETAIL_MESSAGES, body.detail)) {
      return API_DETAIL_MESSAGES[body.detail] ?? SERVER_TROUBLE;
    }
    if (typeof body?.detail === "string" && SAFETY_DETAILS.has(body.detail)) {
      return SAFETY_UNAVAILABLE;
    }
  } catch {
    // An unreadable refusal still gets fixed web copy.
  }
  return SERVER_TROUBLE;
}
const BAD_REPLY = "Tilo sent a reply this page could not read.";
/** A8: how long a start waits for the intake's reply before the person is told, instead of a spinner for ever.
 * The Director's brief takes up to about a minute; the intake's own provider timeouts sit inside this. */
export const INTAKE_TIMEOUT_MS = 120_000;
const TOOK_TOO_LONG =
  "Tilo is taking too long to answer. Nothing is shown as started; check your worlds before you try again.";

const INTAKE_COMMITTED =
  "This task was already submitted. Check your worlds before starting another task.";

function isIntakeCommitted(status: number, text: string): boolean {
  if (status !== 409) return false;
  try {
    return (
      (JSON.parse(text) as { detail?: { code?: unknown } } | null)?.detail?.code ===
      "intake_already_committed"
    );
  } catch {
    return false;
  }
}
/** STARTER-1: the recorded sample project (`tilo_api.sample_world`); its path is read-only. */
const SAMPLE_PATH = "/worlds/w_sample_village_basic";
const SAMPLE_SIMULATED =
  "This is a recorded sample replay, so your answer was not sent. Nothing here can be approved.";
const GENERIC_4XX: Readonly<Record<number, string>> = {
  401: "You need to sign in to do this.",
  403: "You do not have access to this.",
  402: "A usage limit has been reached, so nothing was started.",
  404: "Tilo could not find that.",
  409: "That cannot be done right now.",
  429: "Tilo is busy right now. Wait a moment and try again.",
};
const OUT_OF_DATE = "This server is out of date for live runs.";
const NOT_BUILT = "Tilo has not built this world yet.";
const NO_WORLD_BUILT = "This run ended before its world was built.";
const SLOW_WORLD = "Tilo is taking longer than expected to build this world.";
/** A bare lower-case token such as `demo_runs_busy` or `cap_reached`: a code, never shown as it is. */
const CODE_WORD = /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+$/;
/** FastAPI's stock texts: not written for people, so the status sentence is used instead. */
const STOCK = new Set(["Not Found", "Forbidden", "Unauthorized", "Conflict", "Bad Request"]);

/** NFR-22: one display boundary for Park. Only approved copy or mapped wire codes;
 * never arbitrary exceptions/server text, URLs, status numbers or credentials. */
export function displayApiError(error: unknown): string {
  if (!(error instanceof TiloApiError)) return SERVER_TROUBLE;
  if (error.replayOnly) return REPLAY_ONLY;
  if (error.write && error.retryable && (error.status === null || error.status >= 500)) {
    return "We could not confirm it. Reload before trying again.";
  }
  const reasons: Readonly<Record<string, string>> = {
    ...API_DETAIL_MESSAGES,
    write_unconfirmed: "We could not confirm it. Reload before trying again.",
    not_configured: NOT_CONFIGURED,
    unavailable: "This feature is unavailable right now. Try again in a moment.",
    body_too_large: "This is too large to send. Reduce its size and try again.",
    store_unavailable: "Stored information is unavailable. Try again in a moment.",
    allowance_capped: "Your allowance is used up. Try again when it resets.",
    spend_cap_reached: "Your spending limit has been reached.",
    rate_limited: "Too many requests. Wait a moment and try again.",
    version_conflict: "This changed while you were working. Reload and try again.",
    demo_read_only: "This is a sample. It cannot change your information.",
    invalid_recipients: "Choose people from this meeting before trying again.",
  };
  const mapped = [error.code, error.refusal, error.message]
    .filter((code): code is string => code !== null)
    .find((code) => Object.hasOwn(reasons, code));
  if (mapped) return reasons[mapped] ?? SERVER_TROUBLE;
  const approved = new Set([
    UNREACHABLE,
    SERVER_TROUBLE,
    REPLAY_ONLY,
    SAFETY_UNAVAILABLE,
    NOT_CONFIGURED,
    BAD_REPLY,
    INTAKE_COMMITTED,
    OUT_OF_DATE,
    NOT_BUILT,
    NO_WORLD_BUILT,
    SLOW_WORLD,
    ...Object.values(GENERIC_4XX),
    ...ANSWER_REASONS.values(),
    ...Object.values(API_DETAIL_MESSAGES),
  ]);
  if (approved.has(error.message)) return error.message;
  if (error.status === null) return UNREACHABLE;
  if (error.status === 429) return reasons.rate_limited ?? SERVER_TROUBLE;
  if (error.status === 422) return "Check the information and try again.";
  return GENERIC_4XX[error.status] ?? SERVER_TROUBLE;
}

/** A card answer's `{outcome: "rejected", reason}` code, in words. The code is not for people. */
const ANSWER_REASONS = new Map([
  ["already_resolved", "This card was already answered."],
  ["card_not_found", "Tilo could not find that card."],
  ["forbidden", "You do not have access to answer this card."],
  ["pin_required", "This answer needs a PIN, which this page cannot take."],
  ["busy", "Tilo is busy with this card. Try again in a moment."],
  ["invalid_option", "That option is not offered on this card."],
  ["invalid_channel", "This answer cannot be sent from the web."],
  ["channel_not_permitted", "This answer cannot be sent from the web."],
]);

/** The server's sentence only when it is a short plain string (`detail`, or the intake limits'
 * `error`); lists, codes, markup and anything long fall back to a sentence of ours. */
export function reasonOf(status: number, text: string): string {
  let said: unknown;
  try {
    const body: unknown = JSON.parse(text);
    if (body && typeof body === "object") {
      const { detail, error, reason, outcome } = body as Record<string, unknown>;
      const coded = typeof reason === "string" ? ANSWER_REASONS.get(reason) : undefined;
      if (coded) return coded;
      said = typeof detail === "string" ? detail : error;
      if (said === undefined && Array.isArray(detail)) {
        // SIMPLE-RUN-1: a 422 whose detail is a list of {loc, msg}: only a sentence the API's own validator wrote
        // ("Value error, <sentence>"); pydantic's stock texts ("Field required") are never shown.
        const first = (detail[0] as { msg?: unknown } | undefined)?.msg;
        if (typeof first === "string" && first.startsWith("Value error, "))
          said = first.slice("Value error, ".length);
      }
      if (status === 422 && outcome === "rejected") said = reason; // the fields route's plain reason (L6c)
    }
  } catch {
    said = undefined;
  }
  if (typeof said === "string" && Object.hasOwn(API_DETAIL_MESSAGES, said)) {
    return API_DETAIL_MESSAGES[said] ?? SERVER_TROUBLE;
  }
  if (
    typeof said === "string" &&
    said.length > 0 &&
    said.length <= 200 &&
    !/[<>{}]/.test(said) &&
    !STOCK.has(said) &&
    !CODE_WORD.test(said) // a stable code (`demo_runs_busy`) is for the page, not for people
  ) {
    return said;
  }
  return GENERIC_4XX[status] ?? "Tilo could not accept that.";
}

/** SEC-16: the one refusal the lifetime-cap pop-up is keyed on (403 `spend_cap_reached`); every other limit differs. */
export function isLifetimeCap(error: unknown): boolean {
  return (
    error instanceof TiloApiError && error.status === 403 && error.code === "spend_cap_reached"
  );
}

/** The refusal's `code` only when it is a short lower-case token (SEC-15); anything else is null. */
function codeOf(text: string): string | null {
  try {
    const code = (JSON.parse(text) as { code?: unknown } | null)?.code;
    return typeof code === "string" && /^[a-z][a-z0-9_]{0,39}$/.test(code) ? code : null;
  } catch {
    return null;
  }
}

/** True only for a 503 whose JSON says `replay_only: true` (the string "true" or 1 do not count). */
function isReplayOnly(status: number, text: string): boolean {
  if (status !== 503) return false;
  try {
    return (JSON.parse(text) as { replay_only?: unknown } | null)?.replay_only === true;
  } catch {
    return false;
  }
}

/** The window is phone-width: the one breakpoint the shell uses for mobile web (App.tsx). */
const onPhone = (): boolean =>
  typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches === true;

/** What `GET /worlds/{id}/events` returns: the stored event. An up-to-date server includes `v`,
 * `world_id`, `run_id` and `item` (CL-INT-4); the Event type minus those, never a copy. */
type EventView = Omit<Event, "v" | "world_id" | "run_id" | "item"> &
  Partial<Pick<Event, "v" | "world_id" | "run_id" | "item">>;
type CompleteView = EventView & Pick<Event, "run_id" | "item">;

/** A row the client may hand on (HR-1): it names its run and says what it carries (`item` is
 * present, null or not). Neither is ever filled in here. A row naming another world is refused. */
const isComplete = (e: EventView, worldId: string): e is CompleteView =>
  typeof e.run_id === "string" &&
  e.run_id !== "" &&
  "item" in e &&
  (e.world_id === undefined || e.world_id === worldId);

const isEventView = (e: unknown): e is EventView =>
  typeof e === "object" &&
  e !== null &&
  typeof (e as EventView).seq === "number" &&
  typeof (e as EventView).id === "string" &&
  typeof (e as EventView).type === "string";

const TERMINAL = new Set(["world.completed", "world.failed"]); // nothing is written after these
const MAX_BACKOFF_MS = 10_000;
/** How long `getLayout` waits for a run to build its world before it says so (a slow Director). */
const LAYOUT_WAIT_MS = 120_000;
/** Polls of a 404 from `/layout` after the run has started (the route reads the same run, so this is rare). */
const LAYOUT_404_POLLS = 5;

const isLayout = (l: unknown): l is Layout => {
  const semantic = (l as Layout | null)?.semantic;
  return typeof l === "object" && l !== null && Array.isArray(semantic?.agents);
};
/** Resolves after `ms`, or at once when `signal` aborts (the caller checks the signal after). */
const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done);
  });
const STOPPED = "This was stopped because the page no longer needs it.";

/** One world's layout call, shared by every page asking for it while it is pending. */
interface LayoutCall {
  readonly promise: Promise<Layout>;
  readonly stop: AbortController;
  /** Callers that passed a signal and have not let go; the call stops when the last one does. */
  holders: number;
  settled: boolean;
}

/** What the event polls of one world have shown so far, for `getLayout` to wait on instead of
 * polling on a timer of its own. */
interface Feed {
  readonly types: Set<string>;
  /** The latest poll's failure, cleared by the next good poll. */
  failure: TiloApiError | null;
  /** Live `subscribeEvents` calls for the world. */
  subs: number;
  readonly waiters: Set<() => void>;
}

export interface HttpClientOptions {
  /** The API origin, e.g. `http://localhost:8080`. */
  readonly baseUrl: string;
  readonly fetch?: typeof fetch;
  /** Gap between event polls (default 1000 ms). */
  readonly pollMs?: number;
  /** SEC-10: the App Check token for the next request, or null. Asked before every request (the SDK
   * caches and refreshes it); a getter that fails or answers null sends the request with no header. */
  readonly appCheckToken?: (() => Promise<string | null>) | undefined;
  /** SEC-15: the Firebase ID token for the next request, or null. Asked before every request (the SDK caches and
   * refreshes it); a getter that fails or answers null, or a token that cannot be a header value, sends the request
   * with no `Authorization` header and the API answers 401. */
  readonly authToken?: (() => Promise<string | null>) | undefined;
}

/** The header the API reads the App Check token from (services/api `appcheck.py`). */
const APP_CHECK_HEADER = "X-Firebase-AppCheck";
const APP_CHECK_TOKEN = /^[A-Za-z0-9._~+/=-]{1,4096}$/;
/** SEC-15: the sign-in token goes in `Authorization: Bearer`; a Firebase ID token is a JWT of a few KB at most. */
const AUTH_TOKEN = /^[A-Za-z0-9._~+/=-]{1,4096}$/;
/** SEC-15 (BQ-SIGNIN-3): sent on a phone-width window, with a token, so the API records `mobile_web`. */
const CHANNEL_HEADER = "X-Tilo-Channel";

/** Why a Quick ask is offered as Thinking instead: the server's closed set (COST-FAST-1), written once, here. */
export const QUICK_REASONS = [
  "attachments",
  "side_effect",
  "deliverable",
  "needs_tools",
  "multi_step",
  "too_long",
  "scenario",
  "unclear",
] as const;
export type QuickReason = (typeof QUICK_REASONS)[number];

/** What the server charged for a Quick answer; each figure only when it was served (no estimate is made here). */
export interface QuickCost {
  credits?: number;
  savedCredits?: number;
}

/** A Quick ask's two answers (services/api COST-FAST-1): the model's text with its cost, or an offer to switch. */
export type QuickIntakeResult =
  | { kind: "answered"; text: string; cost: QuickCost | null }
  | { kind: "switch"; reason: QuickReason };

const figure = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : undefined;

/** The strict reading of a Quick reply: anything else is null (a reply this page cannot read), never a guess. */
function quickOf(body: unknown): QuickIntakeResult | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;
  if (b.mode !== "quick") return null;
  if (b.outcome === "switch_to_thinking") {
    const reason = QUICK_REASONS.find((r) => r === b.reason);
    return reason ? { kind: "switch", reason } : null;
  }
  if (b.outcome !== "answered" || typeof b.text !== "string" || b.text === "") return null;
  const c =
    typeof b.cost === "object" && b.cost !== null ? (b.cost as Record<string, unknown>) : {};
  const cost: QuickCost = {};
  const credits = figure(c.credits);
  const saved = figure(c.saved_credits);
  if (credits !== undefined) cost.credits = credits;
  if (saved !== undefined) cost.savedCredits = saved;
  return { kind: "answered", text: b.text, cost: Object.keys(cost).length > 0 ? cost : null };
}

// Shared by the session's clients so Connectors and World coalesce the first read.
// Only an explicit not-configured result is retained; other failures are evicted.
const connectorSessions = new WeakMap<object, Map<string, Promise<unknown>>>();

export class HttpClient implements TiloClient, SchedulesApi, FieldsApi, ItemApi {
  private readonly base: string;
  private readonly connectorScope: object;
  private readonly fetchFn: typeof fetch;
  private readonly pollMs: number;
  private readonly appCheckToken: (() => Promise<string | null>) | undefined;
  private readonly authToken: (() => Promise<string | null>) | undefined;
  private readonly cardWorlds = new Map<string, string>(); // card -> world, from listCards
  private readonly cardChannels = new Map<string, Card["answer_channels"]>(); // card -> channels it lists
  private readonly layouts = new Map<string, LayoutCall>(); // a run's layout never changes
  private readonly approaches = new Map<string, Promise<ApproachesResult>>(); // in flight only
  private readonly feeds = new Map<string, Feed>();
  private readonly missing = new Set<string>(); // worlds whose events answered 404
  private readonly missingListeners = new Set<() => void>();
  // Keep only the current uncertain intent. File identity matters: same metadata can hide different bytes.
  private intakeIntent:
    | {
        text: string;
        files: File[];
        mode: "quick" | undefined;
        key: string;
        pending?: Promise<IntakeResult | QuickIntakeResult> | undefined;
      }
    | undefined;

  constructor(options: HttpClientOptions) {
    this.base = options.baseUrl.trim().replace(/\/+$/, "");
    this.connectorScope = options.authToken ?? options.fetch ?? fetch;
    // redirect: "error": the API never redirects a call, so one that does (a stray proxy, a hijacked path) is an error, not a
    // detour that would carry the sign-in and App Check tokens to another address (SEC-10)
    this.fetchFn = options.fetch ?? ((url, init) => fetch(url, { ...init, redirect: "error" }));
    this.pollMs = options.pollMs ?? 1000;
    this.appCheckToken = options.appCheckToken;
    this.authToken = options.authToken;
  }

  /** `init` with `Authorization: Bearer <ID token>` when there is a token (SEC-15). Never throws: no token is no header. */
  private async withAuth(init: RequestInit): Promise<RequestInit> {
    if (!this.authToken) return init;
    let token: string | null = null;
    try {
      token = await this.authToken();
    } catch {
      return init;
    }
    // Anything that is not base64url characters and dots would make `fetch` throw (a bad header value), and the call
    // would fail as unreachable; it goes out with no header instead.
    if (typeof token !== "string" || !AUTH_TOKEN.test(token)) return init;
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (onPhone()) headers.set(CHANNEL_HEADER, "mobile_web");
    return { ...init, headers };
  }

  /** `init` with the App Check header when there is a token (SEC-10). Never throws: no token is no header. */
  private async withAppCheck(init: RequestInit): Promise<RequestInit> {
    if (!this.appCheckToken) return init;
    let token: string | null = null;
    try {
      token = await this.appCheckToken();
    } catch {
      return init;
    }
    // A token is a JWT: base64url characters and dots. Anything else would make `fetch` throw (a bad header
    // value) and the call would fail as unreachable, so it goes out with no header instead.
    if (typeof token !== "string" || !APP_CHECK_TOKEN.test(token)) return init;
    const headers = new Headers(init.headers);
    headers.set(APP_CHECK_HEADER, token);
    return { ...init, headers };
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    write = false,
    decode?: (response: Response) => Promise<T>,
  ): Promise<T> {
    let res: Response;
    // A8: the intake is the one call a person waits on in front of a spinner, so it has an end.
    const stop = path === "/intake" ? new AbortController() : null;
    let late = false;
    const timer = stop
      ? setTimeout(() => {
          late = true;
          stop.abort();
        }, INTAKE_TIMEOUT_MS)
      : null;
    try {
      const sent = await this.withAuth(await this.withAppCheck(init));
      res = await this.fetchFn(
        `${this.base}${path}`,
        stop ? { ...sent, signal: stop.signal } : sent,
      );
    } catch {
      if (late) throw new TiloApiError(TOOK_TOO_LONG, null, true, write);
      throw new TiloApiError(UNREACHABLE, null, true, write); // the cause (host, port) is not for people
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
    if (!res.ok) {
      // Read 503's known refusal values or a 4xx; other 5xx are not awaited.
      if (res.status >= 500 && res.status !== 503) {
        if (res.status === 502) {
          // SIMPLE-RUN-1: the Director's two known failures are said as the API words them (an exact allow-list: no
          // other server text is ever shown), so the person is told which step stopped.
          const said = await res
            .text()
            .then((t) => (JSON.parse(t) as { detail?: unknown } | null)?.detail)
            .catch(() => undefined);
          if (typeof said === "string" && DIRECTOR_DETAILS.has(said)) {
            throw new TiloApiError(said, 502, true, write);
          }
        }
        throw new TiloApiError(SERVER_TROUBLE, res.status, true, write);
      }
      const body = await res.text().catch(() => "");
      if (path === "/intake" && isIntakeCommitted(res.status, body)) {
        throw new TiloApiError(INTAKE_COMMITTED, 409, false, write, "intake_already_committed");
      }
      if (isReplayOnly(res.status, body)) {
        throw new TiloApiError(REPLAY_ONLY, 503, false, write, codeOf(body), true);
      }
      const refusal = refusalOf(body);
      if (res.status >= 500) {
        throw new TiloApiError(
          unavailableMessage(body),
          res.status,
          true,
          write,
          codeOf(body),
          false,
          refusal,
        );
      }
      throw new TiloApiError(
        reasonOf(res.status, body),
        res.status,
        false,
        write,
        codeOf(body),
        false,
        refusal,
      );
    }
    if (res.status === 204) return undefined as T; // no content: nothing to read
    try {
      return decode ? await decode(res) : ((await res.json()) as T);
    } catch {
      throw new TiloApiError(BAD_REPLY, res.status, true, write);
    }
  }

  /** A plain GET of `path`, decoded as JSON, with the same typed failures as every other call (WIRE-1). */
  getJson(path: string): Promise<unknown> {
    if (path === "/v1/plate" || path === "/v1/people") return this.readPerson(path);
    if (path === "/v1/connectors") {
      let session = connectorSessions.get(this.connectorScope);
      if (!session) {
        session = new Map();
        connectorSessions.set(this.connectorScope, session);
      }
      const cached = session.get(this.base);
      if (cached) return cached;
      const cache = session;
      const read = this.request<unknown>(path, {}, false, async (response) => {
        const body = await response.json();
        // The wire body remains the existing connector contract; the header carries
        // only the exact configuration refusal, never arbitrary error text.
        if (
          response.headers.get("X-Tilo-Meeting-Host") === "not_configured" &&
          Array.isArray(body?.connectors)
        ) {
          for (const row of body.connectors) {
            if (row?.id === "meeting_host" && row.state_known === false)
              row.unavailable_reason = "not_configured";
          }
        }
        return body;
      }).then(
        (body) => {
          const rows = (body as { connectors?: unknown } | null)?.connectors;
          const unavailable =
            Array.isArray(rows) &&
            rows.some(
              (row) =>
                row?.id === "meeting_host" &&
                row.state_known === false &&
                row.unavailable_reason === "not_configured",
            );
          if (!unavailable) cache.delete(this.base);
          return body;
        },
        (error: unknown) => {
          cache.delete(this.base);
          throw error;
        },
      );
      cache.set(this.base, read);
      return read;
    }
    return this.request<unknown>(path);
  }

  /** X-RESULT-1: authenticated binary reads use the same refusal handling as JSON reads. */
  getBlob(path: string): Promise<Blob> {
    return this.request(path, { cache: "no-store" }, false, (response) => response.blob());
  }

  private async readPerson(path: string): Promise<unknown> {
    try {
      return await this.request<unknown>(path);
    } catch (error) {
      if (!(error instanceof TiloApiError) || error.status !== 404) throw error;
      const founded = await bootstrapPerson(
        this.base,
        (body) => this.postJson("/v1/people/first", body),
        (refusal) => refusal instanceof TiloApiError && refusal.status === 403,
      );
      if (!founded) throw error; // existing callers render the honest empty plate
      return this.request<unknown>(path); // one reread; never a retry loop
    }
  }

  /** A plain POST of `body` as JSON, decoded as JSON, with the same typed failures and `write` true (WIRE-3). No credentials.
   * `headers` adds request headers (BQ-CTX-TEAMWORLD: an `Idempotency-Key` so a retried create is made once). */
  postJson(path: string, body: unknown, headers?: Record<string, string>): Promise<unknown> {
    return this.post<unknown>(path, body, headers);
  }

  /** A plain PUT of `body` as JSON, decoded as JSON, with the same typed failures and `write` true (FR-SET-01). */
  putJson(path: string, body: unknown): Promise<unknown> {
    const init = {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    };
    return this.request<unknown>(path, init, true);
  }

  /** A JSON write with any method (PUT, DELETE, POST), decoded as JSON, `write` true (TEAM-WEB). No credentials. */
  sendJson(method: string, path: string, body?: unknown): Promise<unknown> {
    const refused = this.refusedSample(path);
    if (refused) return refused;
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.headers = { "content-type": "application/json" };
      init.body = JSON.stringify(body);
    }
    return this.request<unknown>(path, init, true);
  }

  /** A plain DELETE of `path`, decoded as JSON, with `write` true (ADR-0041 model key removal). */
  deleteJson(path: string): Promise<unknown> {
    return this.request<unknown>(path, { method: "DELETE" }, true);
  }

  /** STARTER-1: the sample project is a recorded replay. A write for it is refused here and never sent: no
   * request leaves for it, whoever asks. Nothing is simulated. */
  private refusedSample(path: string): Promise<never> | null {
    if (path !== SAMPLE_PATH && !path.startsWith(`${SAMPLE_PATH}/`)) return null;
    return Promise.reject(
      new TiloApiError(SAMPLE_SIMULATED, null, false, false, "sample_is_a_replay"),
    );
  }

  private post<T>(path: string, body: unknown, headers?: Record<string, string>): Promise<T> {
    const refused = this.refusedSample(path);
    if (refused) return refused;
    const init = {
      method: "POST",
      headers: { ...headers, "content-type": "application/json" },
      body: JSON.stringify(body),
    };
    return this.request<T>(path, init, true);
  }

  /**
   * `POST /intake`. With no `mode` it is exactly the legacy call (the server reads an absent mode as Thinking);
   * "quick" (COST-FAST-1) returns a direct answer or an offer to switch, and makes no task.
   */
  submitIntake(text: string, files: File[]): Promise<IntakeResult>;
  submitIntake(text: string, files: File[], mode: "quick"): Promise<QuickIntakeResult>;
  async submitIntake(
    text: string,
    files: File[],
    mode?: "quick",
  ): Promise<IntakeResult | QuickIntakeResult> {
    let intent = this.intakeIntent;
    if (
      !intent ||
      intent.text !== text ||
      intent.mode !== mode ||
      intent.files.length !== files.length ||
      !intent.files.every((file, i) => file === files[i])
    ) {
      intent = { text, files: [...files], mode, key: crypto.randomUUID() };
      this.intakeIntent = intent;
    }
    // QA-11: sharing the key alone still sends two POSTs while the first is pending.
    if (intent.pending) return intent.pending;
    const pending = this.sendIntake(text, intent.files, mode, intent.key);
    intent.pending = pending;
    try {
      const result = await pending;
      if (this.intakeIntent === intent) this.intakeIntent = undefined;
      return result;
    } catch (error) {
      // A network/5xx/unreadable reply can follow a committed write: a manual retry keeps the key.
      if (error instanceof TiloApiError && !error.retryable && this.intakeIntent === intent) {
        this.intakeIntent = undefined;
      }
      throw error;
    } finally {
      intent.pending = undefined;
    }
  }

  private async sendIntake(
    text: string,
    files: File[],
    mode: "quick" | undefined,
    key: string,
  ): Promise<IntakeResult | QuickIntakeResult> {
    const form = new FormData();
    form.append("text", text);
    for (const file of files) form.append("files", file);
    const init = { method: "POST", body: form, headers: { "Idempotency-Key": key } };
    if (mode === "quick") {
      form.append("mode", mode);
      const body = await this.request<unknown>("/intake", init, true);
      const quick = quickOf(body);
      if (!quick) throw new TiloApiError(BAD_REPLY, 200, true, true);
      return quick;
    }
    const r = await this.request<
      Omit<IntakeResult, "files"> & {
        files: Array<{ filename: string; status: "ok" | "failed"; safety_flagged: boolean }>;
      }
    >("/intake", init, true);
    return {
      task_id: r.task_id,
      brief: r.brief,
      questions: r.questions,
      // The API's `error` and `safety_reason` texts can quote the file or the screen's findings,
      // so a fixed sentence is shown instead.
      files: r.files.map((f) => ({
        name: f.filename,
        status: f.status,
        safety_flagged: f.safety_flagged,
        reason: f.safety_flagged
          ? "The safety check flagged this file."
          : f.status === "failed"
            ? "Tilo could not read this file."
            : null,
      })),
    };
  }

  answerQuestions(
    taskId: string,
    answers: QuestionAnswer[],
    briefEdits: Partial<Brief>,
  ): Promise<{ brief: Brief }> {
    return this.post(`/tasks/${encodeURIComponent(taskId)}/answers`, {
      answers,
      brief_edits: briefEdits,
    });
  }

  /** Calls for one task that overlap (React's dev double mount) share one request; it is not kept,
   * so a later call sees the answers given since. */
  getApproaches(taskId: string): Promise<ApproachesResult> {
    const running = this.approaches.get(taskId);
    if (running) return running;
    const call = this.request<ApproachesResult>(`/tasks/${encodeURIComponent(taskId)}/approaches`);
    this.approaches.set(taskId, call);
    const done = () => this.approaches.delete(taskId);
    call.then(done, done);
    return call;
  }

  approve(taskId: string, req: ApprovalRequest): Promise<{ world_id: string }> {
    return this.post(`/tasks/${encodeURIComponent(taskId)}/approve`, req);
  }

  /** `GET /worlds/{id}/layout` (FR-WLD-05): the run's own layout, built from its plan, never made up
   * here. The route is a 404 until the run has built it, and a browser logs every 404 as an error, so
   * the world's recorded events are read first and the layout is asked for only once `world.started`
   * is on record (the run builds it before writing that). Until then the call stays pending (a loading
   * state, not a failure); a run that failed first rejects with a plain reason. One call per world is
   * shared and a successful layout is kept; a failure is not, so a retry asks again. */
  getLayout(worldId: string, signal?: AbortSignal): Promise<Layout> {
    let call = this.layouts.get(worldId);
    if (!call && signal?.aborted) return Promise.reject(new TiloApiError(STOPPED, null, false));
    if (!call) {
      const stop = new AbortController();
      const made: LayoutCall = {
        promise: this.awaitLayout(worldId, stop.signal),
        stop,
        holders: 0,
        settled: false,
      };
      call = made;
      this.layouts.set(worldId, made);
      const done = (kept: boolean) => {
        made.settled = true;
        if (!kept && this.layouts.get(worldId) === made) this.layouts.delete(worldId);
      };
      made.promise.then(
        () => done(true),
        () => done(false),
      );
    }
    // A caller with a signal holds the shared call; when the last one lets go (its page left) the
    // call stops polling instead of running on to its deadline. A caller without one never lets go.
    if (signal) {
      const held = call;
      held.holders += 1;
      const release = () => {
        held.holders -= 1;
        if (held.holders > 0 || held.settled) return;
        if (this.layouts.get(worldId) === held) this.layouts.delete(worldId);
        held.stop.abort();
      };
      if (signal.aborted) release();
      else signal.addEventListener("abort", release, { once: true });
    }
    return call.promise;
  }

  /** True once the server has answered 404 for this world's events: the world does not exist. The
   * page says "Not found" on it (App's `useWorldKnown`); the client has stopped polling it. */
  isWorldMissing(worldId: string): boolean {
    return this.missing.has(worldId);
  }

  /** `useSyncExternalStore`'s subscribe for `isWorldMissing`. Returns the unsubscribe. */
  onWorldMissing(listener: () => void): () => void {
    this.missingListeners.add(listener);
    return () => this.missingListeners.delete(listener);
  }

  private feed(worldId: string): Feed {
    let feed = this.feeds.get(worldId);
    if (!feed) {
      feed = { types: new Set(), failure: null, subs: 0, waiters: new Set() };
      this.feeds.set(worldId, feed);
    }
    return feed;
  }

  /** Waits on what the event polls show: the page's own subscription when it has one, else one this
   * call opens and closes itself. No timer of its own but the one deadline, cleared when it ends. */
  private async awaitStarted(worldId: string, signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw new TiloApiError(STOPPED, null, false);
    const feed = this.feed(worldId);
    if (feed.subs === 0) feed.failure = null; // a failure of an earlier, closed subscription is stale
    const own = feed.subs === 0 ? this.subscribeEvents(worldId, () => undefined) : null;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let check: (() => void) | undefined;
    let abort: (() => void) | undefined;
    try {
      await new Promise<void>((resolve, reject) => {
        abort = () => reject(new TiloApiError(STOPPED, null, false));
        if (signal.aborted) return abort();
        signal.addEventListener("abort", abort);
        check = () => {
          if (feed.types.has("world.started")) resolve();
          else if (feed.types.has("world.failed"))
            reject(new TiloApiError(NO_WORLD_BUILT, null, false));
          else if (feed.failure) reject(feed.failure);
        };
        feed.waiters.add(check);
        deadline = setTimeout(
          () => reject(new TiloApiError(SLOW_WORLD, null, true)),
          LAYOUT_WAIT_MS,
        );
        check();
      });
    } finally {
      clearTimeout(deadline);
      if (check) feed.waiters.delete(check);
      if (abort) signal.removeEventListener("abort", abort);
      own?.();
    }
  }

  private async awaitLayout(worldId: string, signal: AbortSignal): Promise<Layout> {
    const id = encodeURIComponent(worldId);
    await this.awaitStarted(worldId, signal);
    for (let tries = 1; ; tries += 1) {
      try {
        if (signal.aborted) throw new TiloApiError(STOPPED, null, false);
        const layout = await this.request<unknown>(`/worlds/${id}/layout`, { signal });
        if (!isLayout(layout)) throw new TiloApiError(BAD_REPLY, 200, true);
        return layout;
      } catch (error) {
        const notYet = error instanceof TiloApiError && error.status === 404;
        if (!notYet) throw error;
        if (tries >= LAYOUT_404_POLLS) throw new TiloApiError(NOT_BUILT, 404, true);
        await sleep(this.pollMs, signal);
      }
    }
  }

  /** Polls `GET /worlds/{id}/events` (the API has no stream or cursor parameter) and hands over only
   * what is past the last seq delivered, in seq order, once per id. A failed poll keeps the cursor
   * and backs off, so the next good one resumes where this stopped. Unknown event types are passed
   * on (HR-5 puts them in the Trace); malformed rows are dropped.
   *
   * A row without `run_id`, or without an `item` key, comes from a server that is out of date: it
   * and everything after it is withheld (nothing is invented), polling stops and `onError` gets a
   * fixed, non-retryable error once. Not part of the TiloClient interface yet (needs the OK). */
  subscribeEvents(
    worldId: string,
    onEvent: (e: Event) => void,
    onError?: (e: TiloApiError) => void,
  ): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let failures = 0;
    const seen = new Map<string, number>(); // id -> seq, only ids at or after the cursor
    const path = `/worlds/${encodeURIComponent(worldId)}/events`;
    const feed = this.feed(worldId);
    feed.subs += 1;
    let open = true;
    const note = (failure: TiloApiError | null) => {
      feed.failure = failure;
      for (const wake of [...feed.waiters]) wake();
    };

    const poll = async () => {
      let delay = this.pollMs;
      let fresh: EventView[] = [];
      try {
        const body = await this.request<{ events?: unknown }>(path);
        const rows = Array.isArray(body.events) ? body.events.filter(isEventView) : [];
        fresh = rows.filter((e) => e.seq > cursor && !seen.has(e.id)).sort((a, b) => a.seq - b.seq);
        failures = 0;
        for (const row of rows) feed.types.add(row.type);
        if (this.missing.delete(worldId))
          for (const listener of [...this.missingListeners]) listener();
        note(null);
      } catch (error) {
        const known =
          error instanceof TiloApiError ? error : new TiloApiError(UNREACHABLE, null, true);
        if (!known.retryable) {
          stopped = true; // 4xx (an unknown world is a 404): it will not change
          if (known.status === 404 && !this.missing.has(worldId)) {
            this.missing.add(worldId);
            for (const listener of [...this.missingListeners]) listener();
          }
          onError?.(known);
        }
        failures += 1;
        delay = Math.min(this.pollMs * 2 ** failures, MAX_BACKOFF_MS);
        note(known);
      }
      for (const view of fresh) {
        if (stopped) return;
        if (!isComplete(view, worldId)) {
          stopped = true;
          const outOfDate = new TiloApiError(OUT_OF_DATE, null, false);
          onError?.(outOfDate);
          note(outOfDate);
          return;
        }
        seen.set(view.id, view.seq);
        cursor = view.seq;
        try {
          // `world_id` is the world this very request asked for (the route's own id, and the API
          // reads only that world's stream) and `v` is the schema's single version, so both are
          // known, not invented. `run_id` and `item` are never filled in.
          onEvent({ v: "1.0", world_id: worldId, ...view });
        } catch {
          // A consumer's own failure must not end the polling; the event counts as delivered.
        }
        if (TERMINAL.has(view.type)) stopped = true;
      }
      for (const [id, seq] of seen) if (seq < cursor) seen.delete(id);
      if (!stopped) timer = setTimeout(poll, delay);
    };
    void poll();
    return () => {
      if (open) feed.subs -= 1;
      open = false;
      stopped = true;
      clearTimeout(timer);
    };
  }

  async listCards(worldId: string): Promise<Card[]> {
    const cards = await this.request<Card[]>(`/worlds/${encodeURIComponent(worldId)}/cards`);
    for (const card of cards) {
      this.cardWorlds.set(card.id, worldId);
      this.cardChannels.set(card.id, card.answer_channels);
    }
    return cards;
  }

  /** The route is per world and `answerCard` is not given one, so the card must have come from
   * `listCards`. The API takes `{option}` and the channel it came from: `answer.context` is not
   * sent. A phone-width window answers as "mobile_web" (FR-HIL-11) when the card lists it; every
   * other answer is "web", the API's default, so no field is sent. */
  async answerCard(cardId: string, answer: CardAnswer): Promise<void> {
    const worldId = this.cardWorlds.get(cardId);
    if (worldId === undefined) {
      throw new TiloApiError("Open the card list again, then answer from there.", null, false);
    }
    await this.post(
      `/worlds/${encodeURIComponent(worldId)}/cards/${encodeURIComponent(cardId)}/answer`,
      this.cardChannels.get(cardId)?.includes("mobile_web") && onPhone()
        ? { option: answer.option_id, channel: "mobile_web" }
        : { option: answer.option_id },
    );
  }

  /** `GET /worlds/{id}/cards/{cid}/fields` (ADR-0035 L6c): what an open fields card asks for. The card must have come
   * from `listCards` (the route is per world). A reply that is not the documented shape is an unreadable reply. */
  async getCardFields(cardId: string): Promise<FieldSpec[]> {
    return await this.cardsOf(this.worldOfCard(cardId)).getCardFields(cardId);
  }

  /** `POST /worlds/{id}/cards/{cid}/fields` `{fields}`: the values go to this one request. A refusal carries the API's
   * own plain reason (422), which `reasonOf` shows when it is short plain text. */
  async supplyCardFields(cardId: string, values: Readonly<Record<string, string>>): Promise<void> {
    return await this.cardsOf(this.worldOfCard(cardId)).supplyCardFields(cardId, values);
  }

  /** `GET /worlds/{id}/cards/{cid}/item` (ADR-0035 L6d): the document a gate card pins, for the owner's show-me. */
  async getCardItem(cardId: string): Promise<PinnedItem> {
    return await this.cardsOf(this.worldOfCard(cardId)).getCardItem(cardId);
  }

  private worldOfCard(cardId: string): string {
    const worldId = this.cardWorlds.get(cardId);
    if (worldId === undefined) {
      throw new TiloApiError("Open the card list again, then answer from there.", null, false);
    }
    return worldId;
  }

  /** The fields and item calls of one world's cards, for a card that names its world itself (the Park Decisions
   * card does, so no `listCards` is needed). Same requests, same auth and refusals as the methods above. */
  cardsOf(worldId: string): FieldsApi & ItemApi {
    const path = (cardId: string, leaf: string) =>
      `/worlds/${encodeURIComponent(worldId)}/cards/${encodeURIComponent(cardId)}/${leaf}`;
    return {
      getCardFields: async (cardId) => {
        const specs = fieldSpecsOf(await this.request<unknown>(path(cardId, "fields")));
        if (!specs) throw new TiloApiError(BAD_REPLY, 200, true);
        return specs;
      },
      supplyCardFields: async (cardId, values) => {
        await this.post(path(cardId, "fields"), { fields: values });
      },
      getCardItem: async (cardId) => {
        const item = pinnedItemOf(await this.request<unknown>(path(cardId, "item")));
        if (!item) throw new TiloApiError(BAD_REPLY, 200, true);
        return item;
      },
    };
  }

  getDelivery(worldId: string): Promise<DeliveryResult> {
    return this.request(`/worlds/${encodeURIComponent(worldId)}/delivery`);
  }

  /** `POST /worlds/{id}/autopilot/stop` (FR-HIL-07): every rule of the world's owner back to L1. The
   * reply is the API's own count; a body that is not that shape is an unreadable reply, never a
   * result. Not on the TiloClient interface (like `pauseWorld`). */
  async stopAutopilot(worldId: string): Promise<StopResult> {
    const result = await this.post<unknown>(
      `/worlds/${encodeURIComponent(worldId)}/autopilot/stop`,
      {},
    );
    if (!isStopResult(result)) throw new TiloApiError(BAD_REPLY, 200, true, true);
    return result;
  }

  /** `POST /worlds/{id}/pause` (FR-WLD-07). Not on the TiloClient interface yet. */
  async pauseWorld(worldId: string): Promise<void> {
    await this.post(`/worlds/${encodeURIComponent(worldId)}/pause`, {});
  }

  /** `POST /v1/meetings/{id}/host` (FR-MTG-09): the owner asks Tilo to host a scheduled bot meeting. The body is
   * always `{}`. The reply is only the meeting's world id; the T3 gate card is then in that world's cards
   * (`listCards`). Nothing is created until the person answers it. Not on the TiloClient interface. */
  async hostMeeting(meetingId: string): Promise<HostStarted> {
    const path = `/v1/meetings/${encodeURIComponent(meetingId)}/host`;
    const result = await this.post<unknown>(path, {});
    if (!isHostStarted(result)) throw new TiloApiError(BAD_REPLY, 200, true, true);
    return { world_id: result.world_id };
  }

  /** `GET /schedules` (FR-AGT-14): the owner's routines. A body that is not `{schedules: [...]}` of
   * readable rows is an unreadable reply, never an empty list. */
  async listSchedules(): Promise<ScheduleView[]> {
    const body = await this.request<{ schedules?: unknown } | null>("/schedules");
    const rows = body?.schedules;
    if (!Array.isArray(rows) || !rows.every(isScheduleView)) {
      throw new TiloApiError(BAD_REPLY, 200, true);
    }
    return rows;
  }

  /** `POST /schedules`: repeat a run the person already approved. */
  createSchedule(req: ScheduleRequest): Promise<ScheduleView> {
    return this.post("/schedules", req);
  }

  /** `PATCH /schedules/{id}`: pause, resume or rename. */
  updateSchedule(id: string, patch: { enabled?: boolean; title?: string }): Promise<ScheduleView> {
    const init = {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    };
    return this.request(`/schedules/${encodeURIComponent(id)}`, init, true);
  }

  /** `POST /v1/feedback` (SEC-16, BQ-FEEDBACK-1): resolves only when the server said `{received: true}`; the uid is the
   * sign-in token's, never the body. No automatic retry. */
  async submitFeedback(words: string): Promise<void> {
    const reply = await this.post<{ received?: unknown } | null>("/v1/feedback", {
      text: words,
      context: "lifetime_cap",
    });
    if (reply?.received !== true) throw new TiloApiError(BAD_REPLY, 200, true, true);
  }

  /** `DELETE /schedules/{id}`: 204 with no body. */
  async deleteSchedule(id: string): Promise<void> {
    await this.request<undefined>(
      `/schedules/${encodeURIComponent(id)}`,
      { method: "DELETE" },
      true,
    );
  }
}
