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
  return {
    what: card.what_happened,
    why: card.why_it_matters,
    action,
    recipients,
    irreversible: gate.irreversible === true,
    options: shown,
  };
}

/** Why a share call did not work, in the few ways the page tells apart. Anything about the token (unknown,
 * another person's, expired, revoked, answered elsewhere) is one line, so the page never says which. */
export type ShareRefusal = "sign_in" | "unavailable" | "paused" | "try_again" | "unreadable";

export function refusalOf(error: unknown): ShareRefusal {
  if (!(error instanceof TiloApiError)) return "try_again";
  if (error.status === 401) return "sign_in";
  if (error.status === 409) return "paused";
  if (error.status === null || error.status >= 500 || error.retryable) return "try_again";
  return "unavailable"; // 400, 403, 404, 410: this link cannot be used by this person now
}

const path = (token: string, tail = ""): string => `/share/${encodeURIComponent(token)}${tail}`;

/** One GET. The result is a view or a refusal, never a throw. */
export async function openShare(
  http: ShareHttp,
  token: string,
): Promise<{ view: GateView } | { refusal: ShareRefusal }> {
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
  try {
    const body = await http.postJson(path(token, "/answer"), { option });
    return rec(body) && body.outcome === "answered" ? "answered" : "unreadable";
  } catch (e) {
    return refusalOf(e);
  }
}

/** The token of `/share/<token>`, or null for any other address. */
export function tokenOf(pathname: string): string | null {
  const m = /^\/share\/([^/]+)\/?$/.exec(pathname);
  if (!m?.[1]) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

/** The sentence for each refusal. */
export const REFUSAL_TEXT: Readonly<Record<ShareRefusal, string>> = {
  sign_in: "Sign in with the account this link was shared with, then open it again.",
  unavailable: "This link is not available.",
  paused: "This is paused right now, so it cannot be answered. Try again later.",
  try_again: "Tilo could not be reached. Nothing was changed. Try again.",
  unreadable: "Tilo sent a reply this page could not read. Nothing was changed.",
};
