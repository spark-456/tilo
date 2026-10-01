import type {
  ArtifactRef,
  Brief,
  Card,
  Credits,
  DeliverableFormat,
  Event,
  Layout,
  PlanApproach,
} from "@tilo/contracts";

export interface AttachmentRef {
  readonly name: string;
  readonly size: number;
  readonly mime: string;
}

export interface ClarifyingQuestion {
  readonly id: string;
  readonly prompt: string;
  readonly options: readonly string[];
  readonly safe_default: string;
}

export interface DeliveryArtifact {
  readonly ref: ArtifactRef;
  readonly title: string;
  readonly format: DeliverableFormat;
  readonly verified: boolean;
}

export interface DeliveryView {
  readonly worldId: string;
  readonly artifacts: readonly DeliveryArtifact[];
  readonly creditsUsed: Credits;
}

export interface TiloClient {
  submitIntake(
    text: string,
    attachments: readonly AttachmentRef[],
  ): Promise<{ taskId: string; brief: Brief; questions: readonly ClarifyingQuestion[] }>;
  answerQuestions(
    taskId: string,
    answers: Readonly<Record<string, string>>,
    briefEdits?: Partial<Brief>,
  ): Promise<{ brief: Brief }>;
  getApproaches(
    taskId: string,
  ): Promise<{ approaches: readonly PlanApproach[]; recommendedId: string }>;
  approve(
    taskId: string,
    approachId: string,
    budgetCap: number,
  ): Promise<{ worldId: string; runId: string }>;
  getLayout(worldId: string): Promise<Layout>;
  subscribeEvents(worldId: string, onEvent: (e: Event) => void): () => void;
  listCards(worldId: string): Promise<readonly Card[]>;
  answerCard(worldId: string, cardId: string, optionId: string, context?: string): Promise<void>;
  getDelivery(worldId: string): Promise<DeliveryView>;
}
