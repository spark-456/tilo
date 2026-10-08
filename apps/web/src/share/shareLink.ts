// FR-HIL-12: an Approver answers a gate from a shared link after sign-in. The API (services/api sharing.py,
// tests/API_FR_HIL_12.md) does every check: who the link names, expiry, revocation, the assignment time. The web
// only shows the re-raised gate card it is given and sends the one answer. Nothing here decides authorisation, and
// the token goes into the request path and nowhere else: not a title, a log line, a link or a message.
import { TiloApiError } from "../api/http";

/** The two calls a share needs; `HttpClient` has both. */
export interface ShareHttp {
  getJson(path: string): Promise<unknown>;
  postJson(path: string, body: unknown): Promise<unknown>;
}

export interface GateOption {
  readonly id: string;
  readonly label: string;
  readonly suggested: boolean;
}

/** What the page shows of the gate: the card's own words, the exact action and who it reaches. */
export interface GateView {
  readonly what: string;
  readonly why: string;
  readonly action: string;
  readonly recipients: readonly string[];
  readonly irreversible: boolean;
  /** "label (version 2)" of the stored file the action holds, or null. */
  readonly item: string | null;
  readonly tier: string | null;
  readonly options: readonly GateOption[];
}

const text = (v: unknown): v is string => typeof v === "string" && v !== "";
const rec = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The `{card}` body of `GET /share/{token}` as a gate view; null when it is not a gate card with options. */
export function gateViewOf(body: unknown): GateView | null {
  const card = rec(body) && rec(body.card) ? body.card : null;
  if (!card || card.kind !== "gate" || !rec(card.gate) || !rec(card.gate.action)) return null;
  const { gate } = card;
  const action = (gate.action as Record<string, unknown>).exact;
  const recipients = gate.recipients;
  const options = card.options;
  if (
    !text(card.what_happened) ||
    !text(card.why_it_matters) ||
    !text(action) ||
    !Array.isArray(recipients) ||
    !recipients.every(text) ||
    !Array.isArray(options) ||
    options.length < 2
  )
    return null;
  const shown: GateOption[] = [];
  for (const o of options) {
    if (!rec(o) || !text(o.id) || !text(o.label)) return null;
    shown.push({ id: o.id, label: o.label, suggested: o.suggested === true });
  }
  const ref = (gate.action as Record<string, unknown>).item;
  const item =
    rec(ref) && typeof ref.version === "number"
      ? `${text(ref.label) ? ref.label : "A stored file"} (version ${ref.version})`
      : null;
  return {
    what: card.what_happened,
    why: card.why_it_matters,
    action,
    recipients,
    irreversible: gate.irreversible === true,
    item,
    tier: text(gate.risk_tier) ? gate.risk_tier : null,
    options: shown,
  };
}

/** Why a share call did not work, in the few ways the page tells apart. Anything about the token (unknown,
 * another person's, expired, revoked, answered elsewhere) is one line, so the page never says which. */
export type ShareRefusal =
  | "sign_in"
  | "unavailable"
  | "busy"
  | "try_again"
  | "unreadable"
  | "unconfirmed";

export function refusalOf(error: unknown): ShareRefusal {
  if (!(error instanceof TiloApiError)) return "try_again";
  if (error.status === 401) return "sign_in";
  if (error.status === 409) return "busy";
  if (error.status === null || error.status >= 500 || error.retryable) return "try_again";
  return "unavailable"; // 400, 403, 404, 410: this link cannot be used by this person now
}

/** The shape of a link token (the API makes them with `secrets.token_urlsafe`): anything else is never sent, so
 * "." or ".." can not become a request path. */
const TOKEN = /^[A-Za-z0-9_-]{16,128}$/;
export const isToken = (v: string): boolean => TOKEN.test(v);

const path = (token: string, tail = ""): string => `/share/${encodeURIComponent(token)}${tail}`;

/** One GET. The result is a view or a refusal, never a throw. */
export async function openShare(
  http: ShareHttp,
  token: string,
): Promise<{ view: GateView } | { refusal: ShareRefusal }> {
  if (!isToken(token)) return { refusal: "unavailable" };
  try {
    const view = gateViewOf(await http.getJson(path(token)));
    return view ? { view } : { refusal: "unreadable" };
  } catch (e) {
    return { refusal: refusalOf(e) };
  }
}

/** One POST of the chosen option, never retried: a person answers once. */
export async function answerShare(
  http: ShareHttp,
  token: string,
  option: string,
): Promise<"answered" | ShareRefusal> {
  if (!isToken(token)) return "unavailable";
  try {
    const body = await http.postJson(path(token, "/answer"), { option });
    // The API sends 200 only for an answer; any other body may still have been written (PRD 18.4).
    return rec(body) && body.outcome === "answered" ? "answered" : "unconfirmed";
  } catch (e) {
    // After the send, only a definite refusal (a 4xx) is known not to have been written; the rest may have been.
    const why = refusalOf(e);
    return why === "try_again" || why === "unreadable" ? "unconfirmed" : why;
  }
}

/** The token of `/share/<token>`, or null for any other address. */
export function tokenOf(pathname: string): string | null {
  const m = /^\/share\/([^/]+)\/?$/.exec(pathname);
  if (!m?.[1]) return null;
  try {
    const token = decodeURIComponent(m[1]);
    return isToken(token) ? token : null;
  } catch {
    return null;
  }
}

/** The sentence for each refusal. */
export const REFUSAL_TEXT: Readonly<Record<ShareRefusal, string>> = {
  sign_in: "Sign in with the account this link was shared with, then open it again.",
  unavailable: "This link is not available.",
  busy: "This cannot be answered right now. Nothing was sent. Try again later.",
  try_again: "Tilo could not be reached. Nothing was changed. Try again.",
  unreadable: "Tilo sent a reply this page could not read. Nothing was changed.",
  unconfirmed:
    "We could not confirm your answer. It may have been recorded. Check before trying again.",
};
