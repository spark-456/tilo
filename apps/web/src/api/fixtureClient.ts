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
import { BRIEF_SUPPLIER_COMPARISON } from "./fixtures/brief";
import { CARDS_VALID } from "./fixtures/cards";
import {
  FIXTURE_APPROACHES,
  FIXTURE_DELIVERY,
  FIXTURE_QUESTIONS,
  FIXTURE_TASK_ID,
  FIXTURE_WORLD_ID,
} from "./fixtures/derived";
import { EVENTS_VILLAGE_BASIC } from "./fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "./fixtures/layout";

export interface FixtureClientOptions {
  /** Deterministic latency added to every request, so tests can observe loading states. */
  readonly delayMs?: number;
  /** Replay speed-up for subscribeEvents; the same meaning as the existing `?speed=` param. */
  readonly speed?: number;
}

/** Same rule as the world replay in useWorldFixture.ts: a finite number above 0, else 1. */
export function replaySpeedFromSearch(search: string): number {
  const speed = Number(new URLSearchParams(search).get("speed"));
  return Number.isFinite(speed) && speed > 0 ? speed : 1;
}

/** The longest delay setTimeout honours; a larger one fires at once. */
const MAX_TIMER_MS = 2 ** 31 - 1;

const wait = (ms: number): Promise<void> =>
  ms <= 0
    ? Promise.resolve()
    : new Promise((resolve) => setTimeout(resolve, Math.min(ms, MAX_TIMER_MS)));

/** TiloClient on the typed contract fixtures. Everything it returns is dev data (HR-4, BQ-07). */
export class FixtureClient implements TiloClient {
  private readonly delayMs: number;
  private readonly speed: number;
  private brief: Brief = BRIEF_SUPPLIER_COMPARISON;
  private readonly answered = new Set<string>();

  constructor(options: FixtureClientOptions = {}) {
    this.delayMs = options.delayMs ?? 0;
    this.speed = options.speed ?? 1;
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
    return LAYOUT_VILLAGE_BASIC;
  }

  /** Replays the recorded stream in seq order, following the recorded `ts` gaps divided by the
   * speed (the world replay's timing, HR-6). The returned function stops it. */
  subscribeEvents(_worldId: string, onEvent: (e: Event) => void): () => void {
    const events: readonly Event[] = [...EVENTS_VILLAGE_BASIC].sort((a, b) => a.seq - b.seq);
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const play = (i: number) => {
      const event = events[i];
      if (stopped || !event) return;
      const prev = events[i - 1];
      const gap = prev ? (Date.parse(event.ts) - Date.parse(prev.ts)) / this.speed : 0;
      timer = setTimeout(
        () => {
          if (stopped) return;
          onEvent(event);
          play(i + 1);
        },
        Math.min(Math.max(0, gap), MAX_TIMER_MS), // setTimeout overflows above 2^31-1 ms
      );
    };
    play(0);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
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
}
