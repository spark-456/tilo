// BQ-CTX-TEAMWORLD (ADR-0040 decisions 6 and 10; FR-TEAM-04): the web's one write for a work item, `POST /v1/work-items`
// through the API client. The body carries a `world_id` only when the person chose the world (a personal item names
// none, as every item did before work_item 1.1.0); the owner, the stamps and the due date are the server's. The reply
// is read strictly and "added" is only ever the server's own answer. Nothing here is a sample.
import { type HttpClient, TiloApiError } from "../../../api/http";

export type WorkItemClient = Pick<HttpClient, "postJson">;

export interface NewItem {
  readonly title: string;
  readonly dueText: string;
  /** The world the item is made in, or null for a personal item. */
  readonly worldId: string | null;
}
export interface AddedItem {
  readonly id: string;
  readonly title: string;
  readonly worldId: string | null;
}

const BAD_REPLY = "Tilo sent a reply this page could not read.";
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;

/** A fresh `Idempotency-Key` for one attempt (reused by its retries), or null where the browser has no source. */
export function newAttemptKey(): string | null {
  try {
    return globalThis.crypto?.randomUUID?.() ?? null;
  } catch {
    return null;
  }
}

export async function addWorkItem(
  client: WorkItemClient,
  item: NewItem,
  attemptKey: string | null = null,
): Promise<AddedItem> {
  const due = item.dueText.trim();
  const body = {
    title: item.title.trim(),
    ...(due ? { due_text: due } : {}),
    source: { kind: "manual", ref: null },
    ...(item.worldId ? { world_id: item.worldId } : {}),
  };
  const reply = await client.postJson(
    "/v1/work-items",
    body,
    attemptKey ? { "Idempotency-Key": attemptKey } : undefined,
  );
  const r = typeof reply === "object" && reply !== null ? (reply as Record<string, unknown>) : null;
  const world = r?.world_id ?? null; // an item the server made personal has no world_id (absent or null)
  if (!r || !text(r.id) || !text(r.title) || r.status !== "open" || world !== item.worldId)
    throw new TiloApiError(`${BAD_REPLY} The item may have been added.`, 201, true, true);
  return { id: r.id, title: r.title, worldId: item.worldId };
}

export interface FailurePlan {
  /** Plain words for the person; never a server string. */
  readonly words: string;
  /** True when sending the same thing again can help (nothing was refused for what it said). */
  readonly retry: boolean;
}

/** What a failed create says. The client does not carry a 422's field list, so it is the refusal word that picks. */
export function planFailure(error: unknown): FailurePlan {
  if (!(error instanceof TiloApiError))
    return { words: "Something went wrong and the item may not have been added.", retry: true };
  switch (error.status) {
    case 401:
      return { words: "You need to sign in to add an item.", retry: false };
    case 403:
      return {
        words: "You can only add items to a world you own or one shared with your team.",
        retry: false,
      };
    case 404:
      return { words: "Tilo could not find that world, so nothing was added.", retry: false };
    case 422:
      return {
        words:
          error.refusal === "invalid_record"
            ? "Tilo could not accept that due date. Shorten it or leave it empty."
            : "Tilo could not accept that title or due date. Check them and try again.",
        retry: false,
      };
    case 201:
      return {
        words: `${BAD_REPLY} The item may have been added; check before adding it again.`,
        retry: true,
      };
    default:
      return error.status === null || error.status >= 500
        ? {
            words: `${error.status === null ? "Tilo could not be reached" : "Tilo had a problem on its side"}. The item may not have been added.`,
            retry: true,
          }
        : { words: "Tilo could not accept that. Nothing was added.", retry: false };
  }
}
