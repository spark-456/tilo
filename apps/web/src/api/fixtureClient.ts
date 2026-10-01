import type { Brief, Card, Event, Layout, PlanApproach } from "@tilo/contracts";
import type { AttachmentRef, ClarifyingQuestion, DeliveryView, TiloClient } from "./client";
import {
  FIXTURE_APPROACHES,
  FIXTURE_BRIEF,
  FIXTURE_CARDS,
  FIXTURE_DELIVERY,
  FIXTURE_EVENTS,
  FIXTURE_LAYOUT,
  FIXTURE_QUESTIONS,
} from "./fixtures";

export interface FixtureClientOptions {
  readonly delayMs?: number;
  readonly intervalMs?: number;
}

const wait = (ms: number): Promise<void> =>
  ms <= 0 ? Promise.resolve() : new Promise((resolve) => setTimeout(resolve, ms));

export class FixtureClient implements TiloClient {
  private readonly delayMs: number;
  private readonly intervalMs: number;
  private currentBrief: Brief = FIXTURE_BRIEF;
  private answeredCardIds = new Set<string>();

  constructor(options: FixtureClientOptions = {}) {
    this.delayMs = options.delayMs ?? 30;
    this.intervalMs = options.intervalMs ?? 10;
  }

  async submitIntake(
    text: string,
    _attachments: readonly AttachmentRef[],
  ): Promise<{ taskId: string; brief: Brief; questions: readonly ClarifyingQuestion[] }> {
    await wait(this.delayMs);
    const goal = text.trim().length > 0 ? text.trim() : FIXTURE_BRIEF.goal;
    this.currentBrief = { ...FIXTURE_BRIEF, goal };
    return {
      taskId: "task-1",
      brief: this.currentBrief,
      questions: FIXTURE_QUESTIONS,
    };
  }

  async answerQuestions(
    _taskId: string,
    _answers: Readonly<Record<string, string>>,
    briefEdits?: Partial<Brief>,
  ): Promise<{ brief: Brief }> {
    await wait(this.delayMs);
    this.currentBrief = { ...this.currentBrief, ...briefEdits };
    return { brief: this.currentBrief };
  }

  async getApproaches(
    _taskId: string,
  ): Promise<{ approaches: readonly PlanApproach[]; recommendedId: string }> {
    await wait(this.delayMs);
    const first = FIXTURE_APPROACHES[0];
    return {
      approaches: FIXTURE_APPROACHES,
      recommendedId: first ? first.id : "quick",
    };
  }

  async approve(
    _taskId: string,
    _approachId: string,
    _budgetCap: number,
  ): Promise<{ worldId: string; runId: string }> {
    await wait(this.delayMs);
    return { worldId: "w_village_basic", runId: "r_village_basic_1" };
  }

  async getLayout(_worldId: string): Promise<Layout> {
    await wait(this.delayMs);
    return FIXTURE_LAYOUT;
  }

  subscribeEvents(_worldId: string, onEvent: (e: Event) => void): () => void {
    const sorted = [...FIXTURE_EVENTS].sort((a, b) => a.seq - b.seq);
    let idx = 0;
    let active = true;
    const timer = setInterval(() => {
      if (!active || idx >= sorted.length) {
        clearInterval(timer);
        return;
      }
      const next = sorted[idx];
      idx += 1;
      if (next && active) {
        onEvent(next);
      }
    }, this.intervalMs);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }

  async listCards(_worldId: string): Promise<readonly Card[]> {
    await wait(this.delayMs);
    return FIXTURE_CARDS.filter((c) => !this.answeredCardIds.has(c.id));
  }

  async answerCard(
    _worldId: string,
    cardId: string,
    _optionId: string,
    _context?: string,
  ): Promise<void> {
    await wait(this.delayMs);
    this.answeredCardIds.add(cardId);
  }

  async getDelivery(worldId: string): Promise<DeliveryView> {
    await wait(this.delayMs);
    return { ...FIXTURE_DELIVERY, worldId };
  }
}
