// ADR-0041 (BYOK-5, INERT): the web half of `/v1/org/model-key`, framework-free. Exactly the shapes of
// services/api `byok_routes.py` (GET, PUT, DELETE); nothing here is a contract type, because `org_model_key.schema.json`
// does not exist yet (docs/byok.md, "Needs a contract change" 4). The key is a function argument: it goes into the one
// PUT body and is dropped, never kept, logged or put in a message. Every refusal becomes a fixed word (`problem`); the
// server's text is never shown, so no answer can carry the key back. `saved` is true only after the live answer AND a
// re-read that shows the key (BK-02, BK-06). While `config/byok.yaml` has `enabled: false` the API answers 503
// `not_configured` and the page says "off in this build".
import { TiloApiError } from "./http";

export type ModelKeyState = "none" | "unverified" | "active" | "paused" | "invalid";
export type ModelKeyProblem =
  | "not_configured" // 503 `not_configured`: BYOK is off in this build
  | "sign_in" // 401: no sign-in
  | "reauth" // 401 `reauth_required`: the sign-in is older than 10 minutes (BK-06)
  | "owner_only" // 403: not the org owner, or a session with no directory record (BK-05)
  | "key_refused" // 422 `key_refused`
  | "confirm" // 422 `confirm_required`: the consent version moved
  | "invalid" // 422 `invalid_body`
  | "rate_limited" // 429: 5 widening acts an hour (BK-07)
  | "unavailable" // 5xx, network, an unreadable answer
  | "unconfirmed"; // the answer was good but the re-read did not show it

export interface ModelKeyView {
  /** True only when the answer carried the owner's fields; a member's `{active, label}` is read-only. */
  owner: boolean;
  active: boolean;
  label: string | null;
  state: ModelKeyState | null;
  version: number | null;
  setAt: string | null;
  rotatedAt: string | null;
  dayCapCredits: number | null;
  consentVersion: number | null;
  /** The API's fixed word for why a stored key is not in use (`not_configured`: its bundle left config). */
  lastError: string | null;
}
export type ModelKeyResult =
  | { ok: true; view: ModelKeyView }
  | { ok: false; problem: ModelKeyProblem };

export interface SaveInput {
  bundleId: string;
  /** An API key, or null for a Vertex IAM bundle (then `projectId`). Exactly one is sent (BQ-BYOK-2). */
  key: string | null;
  projectId: string | null;
  dayCapCredits: number;
  fallbackToTilo: boolean;
  consentVersion: number;
}

export interface ModelKeyFlow {
  read(): Promise<ModelKeyResult>;
  save(input: SaveInput): Promise<ModelKeyResult>;
  remove(): Promise<ModelKeyResult>;
}

interface Http {
  getJson(path: string): Promise<unknown>;
  putJson(path: string, body: unknown): Promise<unknown>;
  deleteJson(path: string): Promise<unknown>;
}

export const MODEL_KEY_PATH = "/v1/org/model-key";
const STATES: readonly string[] = ["none", "unverified", "active", "paused", "invalid"];
const rec = (v: unknown): Record<string, unknown> | null =>
  typeof v === "object" && v !== null ? (v as Record<string, unknown>) : null;
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const int = (v: unknown): number | null =>
  typeof v === "number" && Number.isInteger(v) ? v : null;

function viewOf(body: unknown): ModelKeyView | null {
  const b = rec(body);
  if (!b || typeof b.active !== "boolean") return null;
  const state =
    typeof b.state === "string" && STATES.includes(b.state) ? (b.state as ModelKeyState) : null;
  return {
    owner: state !== null,
    active: b.active,
    label: str(b.label),
    state,
    version: int(b.secret_version),
    setAt: str(b.set_at),
    rotatedAt: str(b.rotated_at),
    dayCapCredits: int(b.day_cap_credits),
    consentVersion: int(b.consent_version),
    lastError: str(b.last_error),
  };
}

/** A failure as a fixed word, by status and the server's short code; the message is never read. */
export function problemOf(error: unknown): ModelKeyProblem {
  if (!(error instanceof TiloApiError)) return "unavailable";
  const word = error.code ?? error.refusal;
  if (error.status === 503) return word === "not_configured" ? "not_configured" : "unavailable";
  if (error.status === 401) return word === "reauth_required" ? "reauth" : "sign_in";
  if (error.status === 403) return "owner_only";
  if (error.status === 429) return "rate_limited";
  if (error.status === 422) {
    return word === "key_refused"
      ? "key_refused"
      : word === "confirm_required"
        ? "confirm"
        : "invalid";
  }
  return "unavailable";
}

export function createModelKeyFlow(http: Http): ModelKeyFlow {
  const read = async (): Promise<ModelKeyResult> => {
    try {
      const view = viewOf(await http.getJson(MODEL_KEY_PATH));
      return view ? { ok: true, view } : { ok: false, problem: "unavailable" };
    } catch (e) {
      return { ok: false, problem: problemOf(e) };
    }
  };
  /** The write's own answer must be well formed, then the re-read must show what it claims. */
  const confirmed = async (
    write: () => Promise<boolean>,
    shows: (v: ModelKeyView) => boolean,
  ): Promise<ModelKeyResult> => {
    try {
      if (!(await write())) return { ok: false, problem: "unavailable" };
    } catch (e) {
      return { ok: false, problem: problemOf(e) };
    }
    const again = await read();
    if (!again.ok) return { ok: false, problem: "unconfirmed" };
    return shows(again.view) ? again : { ok: false, problem: "unconfirmed" };
  };
  return {
    read,
    save: (input) =>
      confirmed(
        async () => {
          const body: Record<string, unknown> = {
            confirm: true,
            consent_version: input.consentVersion,
            bundle_id: input.bundleId,
            day_cap_credits: input.dayCapCredits,
            fallback_to_tilo: input.fallbackToTilo,
          };
          if (input.key !== null) body.key = input.key;
          if (input.projectId !== null) body.project_id = input.projectId;
          const answer = rec(await http.putJson(MODEL_KEY_PATH, body));
          return typeof answer?.state === "string" && int(answer.secret_version) !== null;
        },
        (v) => v.state !== null && v.state !== "none",
      ),
    remove: () =>
      confirmed(
        async () => rec(await http.deleteJson(MODEL_KEY_PATH))?.removed === true,
        (v) => v.state === "none" || !v.owner,
      ),
  };
}
