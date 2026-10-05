// The seam between AG-WEB and the Claude lane CL-INT (issue #80). The interface below is
// verbatim from the issue (kept on its lines with biome-ignore); changing a signature needs the
// orchestrator's OK on that issue.
import type { Brief, Card, Event, Layout, PlanApproach } from "@tilo/contracts";

// biome-ignore format: verbatim from issue #80
export interface IntakeFileStatus { name: string; status: "ok" | "failed"; safety_flagged: boolean; reason: string | null }
// biome-ignore format: verbatim from issue #80
export interface ClarifyingQuestion { field: string; text: string; suggested_answers: string[] } // [0] is the Director's guess, used on skip
// biome-ignore format: verbatim from issue #80
export interface IntakeResult { task_id: string; brief: Brief; files: IntakeFileStatus[]; questions: ClarifyingQuestion[] }
// biome-ignore format: verbatim from issue #80
export interface QuestionAnswer { field: string; answer: string | null } // null = skipped; the brief records the assumption
// biome-ignore format: verbatim from issue #80
export interface ApproachesResult { task_id: string; approaches: PlanApproach[]; recommended: string; credit_usd: number }
// biome-ignore format: verbatim from issue #80
export interface ApprovalRequest { approach_id: string; budget_cap: number }
// biome-ignore format: verbatim from issue #80
export interface DeliveredArtifact { id: string; title: string; kind: string; version: number }
// biome-ignore format: verbatim from issue #80
export interface DeliveryResult {
  world_id: string; artifacts: DeliveredArtifact[]; credits_used: number;
  time_saved: { low_min: number; high_min: number } | null; // always shown as an estimate (PRD 18.4)
}
// biome-ignore format: verbatim from issue #80
export interface CardAnswer { option_id: string; context?: string }

// biome-ignore format: verbatim from issue #80
export interface TiloClient {
  submitIntake(text: string, files: File[]): Promise<IntakeResult>;
  answerQuestions(taskId: string, answers: QuestionAnswer[], briefEdits: Partial<Brief>): Promise<{ brief: Brief }>;
  getApproaches(taskId: string): Promise<ApproachesResult>;
  approve(taskId: string, req: ApprovalRequest): Promise<{ world_id: string }>;
  getLayout(worldId: string, signal?: AbortSignal): Promise<Layout>;
  subscribeEvents(worldId: string, onEvent: (e: Event) => void): () => void; // returns unsubscribe
  listCards(worldId: string): Promise<Card[]>;
  answerCard(cardId: string, answer: CardAnswer): Promise<void>;
  getDelivery(worldId: string): Promise<DeliveryResult>;
}
