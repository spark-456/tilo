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
const NO_ROUTE_YET = "This is not available from Tilo's server yet.";
/** FastAPI's stock texts: not written for people, so the status sentence is used instead. */
const STOCK = new Set(["Not Found", "Forbidden", "Unauthorized", "Conflict", "Bad Request"]);

/** The server's sentence only when it is a short plain string (`detail`, or the intake limits'
 * `error`); lists, codes, markup and anything long fall back to a sentence of ours. */
function reasonOf(status: number, text: string): string {
  let said: unknown;
  try {
    const body: unknown = JSON.parse(text);
    if (body && typeof body === "object") {
      const { detail, error } = body as { detail?: unknown; error?: unknown };
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

/** What `GET /worlds/{id}/events` returns for the owner: the stored event minus `v`, `world_id`,
 * `run_id` and `item` (services/api redaction.py). The Event type minus those, never a copy. */
type EventView = Omit<Event, "v" | "world_id" | "run_id" | "item"> &
  Partial<Pick<Event, "v" | "world_id" | "run_id" | "item">>;

const isEventView = (e: unknown): e is EventView =>
  typeof e === "object" &&
  e !== null &&
  typeof (e as EventView).seq === "number" &&
  typeof (e as EventView).id === "string" &&
  typeof (e as EventView).type === "string";

const TERMINAL = new Set(["world.completed", "world.failed"]); // nothing is written after these
const MAX_BACKOFF_MS = 10_000;

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
  private readonly runIds = new Map<string, string>(); // world -> run, from intake
  private readonly cardWorlds = new Map<string, string>(); // card -> world, from listCards

  constructor(options: HttpClientOptions) {
    this.base = options.baseUrl.trim().replace(/\/+$/, "");
    this.fetchFn = options.fetch ?? ((url, init) => fetch(url, init));
    this.pollMs = options.pollMs ?? 1000;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchFn(`${this.base}${path}`, init);
    } catch {
      throw new TiloApiError(UNREACHABLE, null, true); // the cause (host, port) is not for people
    }
    if (!res.ok) {
      if (res.status >= 500) throw new TiloApiError(SERVER_TROUBLE, res.status, true);
      throw new TiloApiError(
        reasonOf(res.status, await res.text().catch(() => "")),
        res.status,
        false,
      );
    }
    try {
      return (await res.json()) as T;
    } catch {
      throw new TiloApiError(BAD_REPLY, res.status, true);
    }
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async submitIntake(text: string, files: File[]): Promise<IntakeResult> {
    const form = new FormData();
    form.append("text", text);
    for (const file of files) form.append("files", file);
    const r = await this.request<
      Omit<IntakeResult, "files"> & {
        world_id?: string;
        run_id?: string;
        files: Array<{
          filename: string;
          status: "ok" | "failed";
          safety_flagged: boolean;
          safety_reason: string | null;
        }>;
      }
    >("/intake", { method: "POST", body: form });
    if (r.world_id && r.run_id) this.runIds.set(r.world_id, r.run_id);
    return {
      task_id: r.task_id,
      brief: r.brief,
      questions: r.questions,
      // The API's own error text for a failed file can quote the file, so it is not passed on.
      files: r.files.map((f) => ({
        name: f.filename,
        status: f.status,
        safety_flagged: f.safety_flagged,
        reason: f.safety_flagged
          ? (f.safety_reason ?? "The safety check flagged this file.")
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

  /** needs API route: a read of the world's Layout. services/api has none (the run builds the
   * layout and keeps it in memory), and the web never invents a route. */
  getLayout(_worldId: string): Promise<Layout> {
    return Promise.reject(new TiloApiError(NO_ROUTE_YET, null, false));
  }

  /** Polls `GET /worlds/{id}/events` (the API has no stream or cursor parameter) and hands over only
   * what is past the last seq delivered, in seq order, once per id. A failed poll keeps the cursor
   * and backs off, so the next good one resumes where this stopped. Unknown event types are passed
   * on (HR-5 puts them in the Trace); malformed rows are dropped. */
  subscribeEvents(worldId: string, onEvent: (e: Event) => void): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let failures = 0;
    const seen = new Set<string>();
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
        if (view.seq <= cursor || seen.has(view.id)) continue;
        seen.add(view.id);
        cursor = view.seq;
        onEvent({
          v: "1.0",
          world_id: worldId,
          run_id: this.runIds.get(worldId) ?? "", // needs API change: the view omits run_id
          item: null, // needs API change: the view omits item
          ...view,
        });
        if (TERMINAL.has(view.type)) stopped = true;
      }
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
