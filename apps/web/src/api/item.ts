// ADR-0035 L6d (FR-CON-02): the web half of the owner-only show-me route. `GET /worlds/{id}/cards/{cid}/item` returns
// the document a gate card pins as `{kind, ...allowlisted fields, recipients?}`. Here it becomes the JSON text
// `ItemDocumentView` decodes and the recipients the card names. Anything else is an unreadable reply, never shown.

export interface PinnedItem {
  /** The pinned item's JSON text (the view decodes it; a string is only ever rendered as text). */
  readonly document: string;
  /** Who the entry reaches, from the gate card. */
  readonly recipients: readonly string[];
}

/** The one call a gate sheet needs; `HttpClient` has it, the fixture client does not (nothing is pinned offline). */
export interface ItemApi {
  getCardItem(cardId: string): Promise<PinnedItem>;
}

export const isItemApi = (v: unknown): v is ItemApi =>
  typeof (v as Partial<ItemApi> | null)?.getCardItem === "function";

const KINDS = new Set(["email", "file", "calendar_event"]);
const DOCUMENT_MAX = 65_536; // the server's own cap on a shown document
const RECIPIENTS_MAX = 50;

/** The item of a reply, or null when it is not a document of the three kinds with text fields only. */
export function pinnedItemOf(body: unknown): PinnedItem | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const { recipients, ...document } = body as Record<string, unknown>;
  if (typeof document.kind !== "string" || !KINDS.has(document.kind)) return null;
  if (
    recipients !== undefined &&
    !(Array.isArray(recipients) && recipients.length <= RECIPIENTS_MAX)
  )
    return null;
  if (recipients?.some((r: unknown) => typeof r !== "string")) return null;
  const text = JSON.stringify(document);
  if (text.length > DOCUMENT_MAX) return null;
  return { document: text, recipients: (recipients as string[] | undefined) ?? [] };
}
