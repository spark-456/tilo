// CL-INT-3: the HTTP TiloClient over the services/api routes (API_CL_INT_1.md, API_CL_INT_2.md).
// Request and response shapes are the contract types re-exported by ./client; nothing here
// restates a contract. No sign-in: the API's own principal dependency decides (no credentials are
// held or sent from here).
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

/** What a person reads when a call fails (PRD 18.4). `retryable` is true for 5xx and for network
 * or unreadable-reply failures; a 4xx carries a reason and retrying the same call will not help. */
export class TiloApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly retryable: boolean,
    /** The call changes something on the server: a retryable failure may still have happened there. */
    readonly write = false,
  ) {
    super(message);
    this.name = "TiloApiError";
  }
}

const UNREACHABLE = "Tilo could not be reached. Check your connection and try again.";
const SERVER_TROUBLE = "Tilo had a problem on its side.";
const BAD_REPLY = "Tilo sent a reply this page could not read.";
const GENERIC_4XX: Readonly<Record<number, string>> = {
  401: "You need to sign in to do this.",
  403: "You do not have access to this.",
  404: "Tilo could not find that.",
  409: "That cannot be done right now.",
};
const OUT_OF_DATE = "This server is out of date for live runs.";
const NOT_BUILT = "Tilo has not built this world yet.";
const NO_WORLD_BUILT = "This run ended before its world was built.";
const SLOW_WORLD = "Tilo is taking longer than expected to build this world.";
/** FastAPI's stock texts: not written for people, so the status sentence is used instead. */
const STOCK = new Set(["Not Found", "Forbidden", "Unauthorized", "Conflict", "Bad Request"]);

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
function reasonOf(status: number, text: string): string {
  let said: unknown;
  try {
    const body: unknown = JSON.parse(text);
    if (body && typeof body === "object") {
      const { detail, error, reason } = body as Record<string, unknown>;
      const coded = typeof reason === "string" ? ANSWER_REASONS.get(reason) : undefined;
      if (coded) return coded;
      said = typeof detail === "string" ? detail : error;
    }
  } catch {
    said = undefined;
  }
  if (
    typeof said === "string" &&
    said.length > 0 &&
    said.length <= 200 &&
    !/[<>{}]/.test(said) &&
    !STOCK.has(said)
  ) {
    return said;
  }
  return GENERIC_4XX[status] ?? "Tilo could not accept that.";
}

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
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface HttpClientOptions {
  /** The API origin, e.g. `http://localhost:8080`. */
  readonly baseUrl: string;
  readonly fetch?: typeof fetch;
  /** Gap between event polls (default 1000 ms). */
  readonly pollMs?: number;
}

export class HttpClient implements TiloClient {
  private readonly base: string;
  private readonly fetchFn: typeof fetch;
  private readonly pollMs: number;
  private readonly cardWorlds = new Map<string, string>(); // card -> world, from listCards
  private readonly layouts = new Map<string, Promise<Layout>>(); // a run's layout never changes

  constructor(options: HttpClientOptions) {
    this.base = options.baseUrl.trim().replace(/\/+$/, "");
    this.fetchFn = options.fetch ?? ((url, init) => fetch(url, init));
    this.pollMs = options.pollMs ?? 1000;
  }

  private async request<T>(path: string, init: RequestInit = {}, write = false): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchFn(`${this.base}${path}`, init);
    } catch {
      throw new TiloApiError(UNREACHABLE, null, true, write); // the cause (host, port) is not for people
    }
    if (!res.ok) {
      if (res.status >= 500) throw new TiloApiError(SERVER_TROUBLE, res.status, true, write);
      const reason = reasonOf(res.status, await res.text().catch(() => ""));
      throw new TiloApiError(reason, res.status, false, write);
    }
    try {
      return (await res.json()) as T;
    } catch {
      throw new TiloApiError(BAD_REPLY, res.status, true, write);
    }
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    const init = {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    };
    return this.request<T>(path, init, true);
  }

  async submitIntake(text: string, files: File[]): Promise<IntakeResult> {
    const form = new FormData();
    form.append("text", text);
    for (const file of files) form.append("files", file);
    const r = await this.request<
      Omit<IntakeResult, "files"> & {
        files: Array<{ filename: string; status: "ok" | "failed"; safety_flagged: boolean }>;
      }
    >("/intake", { method: "POST", body: form }, true);
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

  getApproaches(taskId: string): Promise<ApproachesResult> {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/approaches`);
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
  getLayout(worldId: string): Promise<Layout> {
    const known = this.layouts.get(worldId);
    if (known) return known;
    const pending = this.awaitLayout(worldId);
    this.layouts.set(worldId, pending);
    pending.catch(() => this.layouts.delete(worldId));
    return pending;
  }

  private async awaitLayout(worldId: string): Promise<Layout> {
    const id = encodeURIComponent(worldId);
    const deadline = Date.now() + LAYOUT_WAIT_MS;
    for (;;) {
      const body = await this.request<{ events?: unknown }>(`/worlds/${id}/events`);
      const types = new Set(
        (Array.isArray(body.events) ? body.events.filter(isEventView) : []).map((e) => e.type),
      );
      if (types.has("world.started")) break;
      if (types.has("world.failed")) throw new TiloApiError(NO_WORLD_BUILT, null, false);
      if (Date.now() >= deadline) throw new TiloApiError(SLOW_WORLD, null, true);
      await sleep(this.pollMs);
    }
    for (let tries = 1; ; tries += 1) {
      try {
        const layout = await this.request<unknown>(`/worlds/${id}/layout`);
        if (!isLayout(layout)) throw new TiloApiError(BAD_REPLY, 200, true);
        return layout;
      } catch (error) {
        const notYet = error instanceof TiloApiError && error.status === 404;
        if (!notYet) throw error;
        if (tries >= LAYOUT_404_POLLS) throw new TiloApiError(NOT_BUILT, 404, true);
        await sleep(this.pollMs);
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

    const poll = async () => {
      let delay = this.pollMs;
      let fresh: EventView[] = [];
      try {
        const body = await this.request<{ events?: unknown }>(path);
        const rows = Array.isArray(body.events) ? body.events.filter(isEventView) : [];
        fresh = rows.filter((e) => e.seq > cursor && !seen.has(e.id)).sort((a, b) => a.seq - b.seq);
        failures = 0;
      } catch (error) {
        if (!(error instanceof TiloApiError) || !error.retryable) stopped = true; // 4xx: it will not change
        failures += 1;
        delay = Math.min(this.pollMs * 2 ** failures, MAX_BACKOFF_MS);
      }
      for (const view of fresh) {
        if (stopped) return;
        if (!isComplete(view, worldId)) {
          stopped = true;
          onError?.(new TiloApiError(OUT_OF_DATE, null, false));
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
      stopped = true;
      clearTimeout(timer);
    };
  }

  async listCards(worldId: string): Promise<Card[]> {
    const cards = await this.request<Card[]>(`/worlds/${encodeURIComponent(worldId)}/cards`);
    for (const card of cards) this.cardWorlds.set(card.id, worldId);
    return cards;
  }

  /** The route is per world and `answerCard` is not given one, so the card must have come from
   * `listCards`. The API takes `{option}` only: `answer.context` is not sent. */
  async answerCard(cardId: string, answer: CardAnswer): Promise<void> {
    const worldId = this.cardWorlds.get(cardId);
    if (worldId === undefined) {
      throw new TiloApiError("Open the card list again, then answer from there.", null, false);
    }
    await this.post(
      `/worlds/${encodeURIComponent(worldId)}/cards/${encodeURIComponent(cardId)}/answer`,
      { option: answer.option_id },
    );
  }

  getDelivery(worldId: string): Promise<DeliveryResult> {
    return this.request(`/worlds/${encodeURIComponent(worldId)}/delivery`);
  }

  /** `POST /worlds/{id}/pause` (FR-WLD-07). Not on the TiloClient interface yet. */
  async pauseWorld(worldId: string): Promise<void> {
    await this.post(`/worlds/${encodeURIComponent(worldId)}/pause`, {});
  }
}
