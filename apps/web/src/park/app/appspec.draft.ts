// replace with generated contract type after ADR-0028 (ADR-0029 landed on contracts/ADR-0029-live-web-media,
// so this module re-exports the generated @tilo/contracts AppSpec types and provides pure validation, scoring,
// topic filtering, publisher formatting and localStorage attempt persistence for LW-14).
import type {
  AppSpec,
  AppSpecOptionId,
  AppSpecOptions,
  AppSpecQuestion,
  AppSpecQuestionId,
  AppSpecSource,
  AppSpecTimer,
  AppSpecTitle,
} from "../api/appSpecTypes";

export type {
  AppSpec,
  AppSpecOptionId,
  AppSpecOptions,
  AppSpecQuestion,
  AppSpecQuestionId,
  AppSpecSource,
  AppSpecTimer,
  AppSpecTitle,
};
export { QUIZ_FIXTURE_PUBLISHERS, QUIZ_FIXTURE_SPEC } from "../api/fixtures/quizAppSpec";

export const OPTION_IDS: readonly AppSpecOptionId[] = ["a", "b", "c", "d", "e", "f"];
const QUESTION_ID_RE = /^q[1-9][0-9]{0,2}$/;
// The contract's patterns, copied: common.schema.json slug and artifact_id. The production bundle does not carry a
// JSON Schema validator (the page CSP forbids eval); pages/QuizPlayer/QuizPlayer.lw14fix.test.tsx checks this module against the schema.
const SLUG_RE = /^[a-z][a-z0-9_]{0,63}$/;
const ARTIFACT_ID_RE = /^art_[0-9A-Za-z_]{1,48}$/;
const TOP_KEYS = new Set(["v", "kind", "title", "theme", "timer", "questions"]);
const QUESTION_KEYS = new Set(["id", "stem", "options", "answer", "topic", "source"]);
const SOURCE_KEYS = new Set(["artifact", "page"]);
const ARTIFACT_KEYS = new Set(["artifact_id", "version", "label"]);

export type AppSpecValidation =
  | { readonly ok: true; readonly spec: AppSpec }
  | { readonly ok: false; readonly reason: string };

export interface QuizReviewItem {
  readonly id: AppSpecQuestionId;
  readonly stem: string;
  readonly options: AppSpecOptions;
  readonly chosen: AppSpecOptionId | null;
  readonly correctAnswer: AppSpecOptionId;
  readonly status: "correct" | "incorrect" | "unanswered";
  readonly topic?: string | undefined;
  readonly source: AppSpecSource;
}

export interface QuizScoreResult {
  readonly correct: number;
  readonly total: number;
  readonly unanswered: number;
  readonly items: readonly QuizReviewItem[];
}

export interface QuizAttemptRecord {
  readonly worldId: string;
  readonly artifactId: string;
  readonly topic: string;
  readonly correct: number;
  readonly total: number;
  readonly unanswered: number;
  readonly reason: "manual" | "time_up";
  readonly answers: Readonly<Record<string, AppSpecOptionId>>;
}

function isPlainRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function hasOnlyKeys(obj: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return Object.keys(obj).every((k) => allowed.has(k));
}

export function validateAppSpec(raw: unknown): AppSpecValidation {
  if (!isPlainRecord(raw)) {
    return { ok: false, reason: "Quiz specification must be a JSON object." };
  }
  if (!hasOnlyKeys(raw, TOP_KEYS)) {
    return { ok: false, reason: "Quiz specification contains unsupported fields." };
  }
  if (raw.v !== "1.0" || raw.kind !== "quiz") {
    return { ok: false, reason: "Unsupported AppSpec version or kind (expected quiz v1.0)." };
  }
  if (typeof raw.title !== "string" || raw.title.length < 1 || raw.title.length > 120) {
    return { ok: false, reason: "Quiz title must be between 1 and 120 characters." };
  }
  if (typeof raw.theme !== "string" || !SLUG_RE.test(raw.theme)) {
    return { ok: false, reason: "Quiz theme must be a valid lower-case slug." };
  }
  if (
    !isPlainRecord(raw.timer) ||
    Object.keys(raw.timer).length !== 1 ||
    typeof raw.timer.seconds !== "number" ||
    !Number.isInteger(raw.timer.seconds) ||
    raw.timer.seconds < 60 ||
    raw.timer.seconds > 21600
  ) {
    return {
      ok: false,
      reason: "Quiz timer must be an integer between 60 and 21,600 seconds.",
    };
  }
  if (!Array.isArray(raw.questions) || raw.questions.length < 1 || raw.questions.length > 200) {
    return { ok: false, reason: "Quiz must contain between 1 and 200 questions." };
  }

  const seenIds = new Set<string>();
  for (const item of raw.questions) {
    if (!isPlainRecord(item) || !hasOnlyKeys(item, QUESTION_KEYS)) {
      return { ok: false, reason: "A question entry contains invalid or unknown fields." };
    }
    if (typeof item.id !== "string" || !QUESTION_ID_RE.test(item.id)) {
      return { ok: false, reason: "Every question id must match q1..q999." };
    }
    if (seenIds.has(item.id)) {
      return { ok: false, reason: `Duplicate question id "${item.id}" is not allowed (AS-01).` };
    }
    seenIds.add(item.id);

    if (typeof item.stem !== "string" || item.stem.length < 1 || item.stem.length > 2000) {
      return { ok: false, reason: `Question ${item.id} has an empty or oversized stem.` };
    }
    if (!isPlainRecord(item.options)) {
      return { ok: false, reason: `Question ${item.id} is missing its options object.` };
    }
    const optKeys = Object.keys(item.options);
    if (
      optKeys.length < 2 ||
      optKeys.length > 6 ||
      !optKeys.every((k) => OPTION_IDS.includes(k as AppSpecOptionId))
    ) {
      return { ok: false, reason: `Question ${item.id} must have 2 to 6 options keyed a..f.` };
    }
    for (let i = 0; i < OPTION_IDS.length; i++) {
      const key = OPTION_IDS[i] as AppSpecOptionId;
      const val = item.options[key];
      if (i < 2 && val === undefined) {
        return { ok: false, reason: `Question ${item.id} must define options a and b.` };
      }
      if (val !== undefined) {
        if (i > 0 && item.options[OPTION_IDS[i - 1] as AppSpecOptionId] === undefined) {
          return { ok: false, reason: `Question ${item.id} options must not skip letters.` };
        }
        if (typeof val !== "string" || val.length < 1 || val.length > 500) {
          return { ok: false, reason: `Question ${item.id} option ${key} text is invalid.` };
        }
      }
    }
    if (
      typeof item.answer !== "string" ||
      !OPTION_IDS.includes(item.answer as AppSpecOptionId) ||
      typeof item.options[item.answer] !== "string"
    ) {
      return {
        ok: false,
        reason: `Question ${item.id} answer must name one of its defined options.`,
      };
    }
    if (item.topic !== undefined && (typeof item.topic !== "string" || !SLUG_RE.test(item.topic))) {
      return { ok: false, reason: `Question ${item.id} topic must be a lower-case slug.` };
    }
    if (!isPlainRecord(item.source) || !hasOnlyKeys(item.source, SOURCE_KEYS)) {
      return { ok: false, reason: `Question ${item.id} must carry a valid source reference.` };
    }
    const art = item.source.artifact;
    if (
      !isPlainRecord(art) ||
      !hasOnlyKeys(art, ARTIFACT_KEYS) ||
      typeof art.artifact_id !== "string" ||
      !ARTIFACT_ID_RE.test(art.artifact_id) ||
      typeof art.version !== "number" ||
      !Number.isInteger(art.version) ||
      art.version < 1 ||
      (art.label !== undefined &&
        (typeof art.label !== "string" || art.label.length < 1 || art.label.length > 80))
    ) {
      return { ok: false, reason: `Question ${item.id} source artifact reference is invalid.` };
    }
    if (
      item.source.page !== undefined &&
      (typeof item.source.page !== "number" ||
        !Number.isInteger(item.source.page) ||
        item.source.page < 1 ||
        item.source.page > 100000)
    ) {
      return { ok: false, reason: `Question ${item.id} source page must be a positive integer.` };
    }
  }

  return { ok: true, spec: raw as unknown as AppSpec };
}

export function optionEntries(
  options: AppSpecOptions,
): readonly (readonly [AppSpecOptionId, string])[] {
  const out: (readonly [AppSpecOptionId, string])[] = [];
  for (const id of OPTION_IDS) {
    const text = options[id];
    if (typeof text === "string") out.push([id, text]);
  }
  return out;
}

export function listTopics(questions: readonly AppSpecQuestion[]): readonly string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const q of questions) {
    if (q.topic && !seen.has(q.topic)) {
      seen.add(q.topic);
      out.push(q.topic);
    }
  }
  return out;
}

export function filterQuestionsByTopic(
  questions: readonly AppSpecQuestion[],
  topic: string,
): readonly AppSpecQuestion[] {
  if (!topic || topic === "all") return questions;
  return questions.filter((q) => q.topic === topic);
}

export function scoreQuizAttempt(
  questions: readonly AppSpecQuestion[],
  answers: Readonly<Record<string, AppSpecOptionId>>,
): QuizScoreResult {
  let correct = 0;
  let unanswered = 0;
  const items: QuizReviewItem[] = questions.map((q) => {
    const chosen = answers[q.id] ?? null;
    if (chosen === null) {
      unanswered += 1;
      return {
        id: q.id,
        stem: q.stem,
        options: q.options,
        chosen: null,
        correctAnswer: q.answer,
        status: "unanswered",
        topic: q.topic,
        source: q.source,
      };
    }
    const isCorrect = chosen === q.answer;
    if (isCorrect) correct += 1;
    return {
      id: q.id,
      stem: q.stem,
      options: q.options,
      chosen,
      correctAnswer: q.answer,
      status: isCorrect ? "correct" : "incorrect",
      topic: q.topic,
      source: q.source,
    };
  });
  return {
    correct,
    total: questions.length,
    unanswered,
    items,
  };
}

export function formatPublisherLine(
  source: AppSpecSource,
  publishers?: Readonly<Record<string, string>>,
): string {
  const artifactId = source.artifact.artifact_id;
  const versionedKey = `${artifactId}@${source.artifact.version}`;
  const publisher =
    publishers?.[versionedKey] ?? publishers?.[artifactId] ?? source.artifact.artifact_id;
  const pageSuffix = source.page !== undefined ? ` · p. ${source.page}` : "";
  return `from ${publisher}${pageSuffix}`;
}

export function formatTimerMmSs(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const mins = Math.floor(clamped / 60);
  const secs = clamped % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

const storageKey = (worldId: string, artifactId: string): string =>
  `tilo.quiz.attempts.${worldId}.${artifactId}`;

export function readQuizAttempts(
  worldId: string,
  artifactId: string,
): readonly QuizAttemptRecord[] {
  try {
    const raw = window.localStorage.getItem(storageKey(worldId, artifactId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as QuizAttemptRecord[]) : [];
  } catch {
    return [];
  }
}

export function saveQuizAttempt(
  worldId: string,
  artifactId: string,
  attempt: QuizAttemptRecord,
): readonly QuizAttemptRecord[] {
  const existing = readQuizAttempts(worldId, artifactId);
  const next = [...existing, attempt];
  try {
    window.localStorage.setItem(storageKey(worldId, artifactId), JSON.stringify(next));
  } catch {
    // localStorage may be unavailable or full in private browsing; keep in-memory state intact
  }
  return next;
}
