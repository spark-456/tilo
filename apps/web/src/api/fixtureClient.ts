import type { Brief, Card, Event, Layout } from "@tilo/contracts";
import { parseSpeed } from "../world/speed";
import { ChunkLoadError } from "./chunkError";
import type {
  ApproachesResult,
  ApprovalRequest,
  CardAnswer,
  DeliveryResult,
  IntakeResult,
  QuestionAnswer,
  TiloClient,
} from "./client";
import { BRIEF_SUPPLIER_COMPARISON } from "./fixtures/brief";
import { CARDS_VALID } from "./fixtures/cards";
import {
  FIXTURE_APPROACHES,
  FIXTURE_DELIVERY,
  FIXTURE_QUESTIONS,
  FIXTURE_TASK_ID,
  FIXTURE_WORLD_ID,
} from "./fixtures/derived";
import type { StopResult } from "./stop";

export interface FixtureClientOptions {
  /** Deterministic latency added to every request, so tests can observe loading states. */
  readonly delayMs?: number;
  /** Replay speed-up for subscribeEvents; the same meaning as the existing `?speed=` param. */
  readonly speed?: number;
}

/** Same rule as the world replay in useWorldFixture.ts (HR-6): above 0 and clamped, else 1. */
export function replaySpeedFromSearch(search: string): number {
  return parseSpeed(new URLSearchParams(search).get("speed"));
}

// The recorded run and its layout are the bulk of the fixtures (NFR-01): imported when a call needs
// them, so the landing route's bundle does not carry them.
const chunk = <T>(what: string, load: () => Promise<T>) =>
  load().catch(() => {
    throw new ChunkLoadError(what);
  });
const loadEvents = () =>
  chunk("The recorded run", () => import("./fixtures/events").then((m) => m.EVENTS_VILLAGE_BASIC));
const loadLayout = () =>
  chunk("The world layout", () => import("./fixtures/layout").then((m) => m.LAYOUT_VILLAGE_BASIC));

/** The longest delay setTimeout honours; a larger one fires at once. */
const MAX_TIMER_MS = 2 ** 31 - 1;

const wait = (ms: number): Promise<void> =>
  ms <= 0
    ? Promise.resolve()
    : new Promise((resolve) => setTimeout(resolve, Math.min(ms, MAX_TIMER_MS)));

/** The world.paused a server would record after Pause all from the web (FR-WLD-07): shaped like
 * contracts/fixtures/events/valid/world.paused.json, one second after the last recorded event. */
function pausedAfter(last: Event): Event {
  const seq = last.seq + 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(seq).padStart(19, "0")}`,
    seq,
    ts: new Date(Date.parse(last.ts) + 1000).toISOString(),
    world_id: last.world_id,
    run_id: last.run_id,
    type: "world.paused",
    actor: "u_owner",
    target: last.world_id,
    level: null,
    district: null,
    item: null,
    severity: "info",
    credits: 0,
    summary: "You paused all work.",
    cause: last.id,
    vis: "all",
    authz: null,
    data: { reason: "pause_all", channel: "web" },
    trace: {
      model_role: null,
      profile: null,
      tokens_in: null,
      tokens_out: null,
      tool: null,
      latency_ms: null,
      archive_ref: null,
    },
  };
}

/** TiloClient on the typed contract fixtures. Everything it returns is dev data (HR-4, BQ-07). */
export class FixtureClient implements TiloClient {
  private readonly delayMs: number;
  private readonly speed: number;
  private brief: Brief = BRIEF_SUPPLIER_COMPARISON;
  private readonly answered = new Set<string>();
  /** Replays still playing; Pause all stops each and records one world.paused (FR-WLD-07). */
  private readonly playing = new Set<() => void>();

  constructor(options: FixtureClientOptions = {}) {
    this.delayMs = options.delayMs ?? 0;
    this.speed = options.speed ?? 1;
  }

  /** The replay speed this client plays at; every screen shows a badge when it is not 1 (HR-6). */
  get replaySpeed(): number {
    return this.speed;
  }

  /** The fixture world is the only one this client knows; any other id is "Not found", never a
   * replay of the village (real clients answer unknown ids themselves). */
  hasWorld(worldId: string): boolean {
    return worldId === FIXTURE_WORLD_ID;
  }

  async submitIntake(_text: string, files: File[]): Promise<IntakeResult> {
    await wait(this.delayMs);
    return {
      task_id: FIXTURE_TASK_ID,
      brief: this.brief,
      files: files.map((f) => ({
        name: f.name,
        status: "ok",
        safety_flagged: false,
        reason: null,
      })),
      questions: FIXTURE_QUESTIONS,
    };
  }

  async answerQuestions(
    _taskId: string,
    _answers: QuestionAnswer[],
    briefEdits: Partial<Brief>,
  ): Promise<{ brief: Brief }> {
    await wait(this.delayMs);
    this.brief = { ...this.brief, ...briefEdits };
    return { brief: this.brief };
  }

  async getApproaches(taskId: string): Promise<ApproachesResult> {
    await wait(this.delayMs);
    return { task_id: taskId, ...FIXTURE_APPROACHES };
  }

  async approve(_taskId: string, _req: ApprovalRequest): Promise<{ world_id: string }> {
    await wait(this.delayMs);
    return { world_id: FIXTURE_WORLD_ID };
  }

  async getLayout(_worldId: string): Promise<Layout> {
    await wait(this.delayMs);
    // The run's events come with the layout, so a missing chunk is said here, where a person is
    // waiting on it, and not as a silently empty stream later.
    const [layout] = await Promise.all([loadLayout(), loadEvents()]);
    return layout;
  }

  /** Replays the recorded stream in seq order, following the recorded `ts` gaps divided by the
   * speed (the world replay's timing, HR-6). The returned function stops it. */
  subscribeEvents(_worldId: string, onEvent: (e: Event) => void): () => void {
    let events: readonly Event[] = [];
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let last: Event | undefined;
    const pause = () => {
      if (stopped || !last || last.seq >= (events[events.length - 1]?.seq ?? 0)) return;
      stopped = true; // the harness stops: nothing is delivered after the pause
      clearTimeout(timer);
      onEvent(pausedAfter(last));
    };
    this.playing.add(pause);
    const play = (i: number) => {
      const event = events[i];
      if (stopped || !event) return;
      const prev = events[i - 1];
      const gap = prev ? (Date.parse(event.ts) - Date.parse(prev.ts)) / this.speed : 0;
      timer = setTimeout(
        () => {
          if (stopped) return;
          last = event;
          onEvent(event);
          play(i + 1);
        },
        Math.min(Math.max(0, gap), MAX_TIMER_MS), // setTimeout overflows above 2^31-1 ms
      );
    };
    void loadEvents().then(
      (recorded) => {
        events = [...recorded].sort((a, b) => a.seq - b.seq);
        play(0);
      },
      () => undefined, // getLayout reports a missing recording; here nothing is invented in its place
    );
    return () => {
      stopped = true;
      clearTimeout(timer);
      this.playing.delete(pause);
    };
  }

  /** Every Stop all autopilot this client received, by world: a test reads what was sent. */
  readonly stopRequests: string[] = [];

  /** Stop all autopilot (FR-HIL-07), not on the TiloClient interface. The fixture world holds no
   * rule that runs on its own (no policy is served), so the honest answer to the call is that
   * nothing was stopped and nothing was already waiting; the call itself is recorded. */
  async stopAutopilot(worldId: string): Promise<StopResult> {
    await wait(this.delayMs);
    this.stopRequests.push(worldId);
    return { stopped: 0, already_l1: 0, confirmations: [], pending: 0 };
  }

  /** Pause all (FR-WLD-07), not on the TiloClient interface. Like the server it stops the run and
   * records world.paused; the screens still wait for that event before claiming anything. */
  async pauseWorld(_worldId: string): Promise<void> {
    await wait(this.delayMs);
    for (const pause of this.playing) pause();
  }

  async listCards(worldId: string): Promise<Card[]> {
    await wait(this.delayMs);
    return CARDS_VALID.filter((c) => !this.answered.has(c.id)).map((c) => ({
      ...c,
      world_id: worldId,
    }));
  }

  async answerCard(cardId: string, _answer: CardAnswer): Promise<void> {
    await wait(this.delayMs);
    this.answered.add(cardId);
  }

  async getDelivery(worldId: string): Promise<DeliveryResult> {
    await wait(this.delayMs);
    return { ...FIXTURE_DELIVERY, world_id: worldId };
  }

  /** The fixture world has no server, so nothing can confirm feedback: it never resolves (no false "Thanks", HR-1). */
  async submitFeedback(_words: string): Promise<void> {
    await wait(this.delayMs);
    throw new Error("The fixture world has no server to receive feedback.");
  }
}
