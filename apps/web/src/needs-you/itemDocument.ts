// ADR-0035 L6c (FR-CON-02): what "Show me" displays of a live item document, the JSON that is hashed, approved and
// sent (BQ-ADR35L5-1): `email` {subject, body_text}, `file` {name, mime_type, content_b64}, `calendar_event` {title,
// start, end, time_zone}. Pure and defensive: every string is data, shown as text and never as markup; a file's base64
// is decoded here for display only (text as text, anything else as its name, type and size).

export type ItemDocument =
  | { readonly kind: "email"; readonly subject: string; readonly body: string }
  | {
      readonly kind: "file";
      readonly name: string;
      readonly mimeType: string;
      readonly bytes: number;
      /** The decoded text, or null for a binary file (shown as "binary file, N bytes"). */
      readonly text: string | null;
    }
  | {
      readonly kind: "calendar_event";
      readonly title: string;
      readonly start: string;
      readonly end: string;
      readonly zone: string;
    }
  | { readonly kind: "unreadable" };

const UNREADABLE: ItemDocument = { kind: "unreadable" };
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const TEXT_TYPES = /^(?:text\/|application\/(?:json|xml|x-yaml|yaml|csv)|image\/svg\+xml$)/i;
/** The most a text file shows; a longer one says how much is left out. */
export const SHOW_MAX = 20_000;

/** The whole document is at most this many characters (the execute contract's 32 KiB item, as JSON and base64). */
export const RAW_MAX = 65_536;
/** `content_b64` is at most this long (the execute contract's maxLength). */
export const B64_MAX = 43_692;

/** Text for display: format characters (bidi overrides and isolates U+202A-202E and U+2066-2069, zero-width and other
 * Cf) are removed, so a shown name or line cannot be made to read as something else. Line breaks stay. */
export const plain = (s: string): string => s.replace(/\p{Cf}/gu, "");

const str = (v: unknown): string | null => (typeof v === "string" ? plain(v) : null);

/** The bytes of a strict base64 string (no whitespace, correct padding), or null. */
export function decodeBase64(b64: string): Uint8Array | null {
  if (b64.length > B64_MAX || b64.length % 4 !== 0 || !BASE64.test(b64)) return null;
  try {
    const raw = atob(b64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

/** UTF-8 text with no NUL byte, or null (a binary file, or text in another encoding). */
function textOf(bytes: Uint8Array): string | null {
  if (bytes.includes(0)) return null;
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

const plainOrNull = (s: string | null): string | null => (s === null ? null : plain(s));

/** The document in `raw` (the pinned item's JSON text), or `unreadable` for anything that is not one of the three. */
export function decodeItemDocument(raw: unknown): ItemDocument {
  let parsed: unknown;
  if (typeof raw === "string" && raw.length > RAW_MAX) return UNREADABLE; // before any parse or decode
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    return UNREADABLE;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return UNREADABLE;
  const d = parsed as Record<string, unknown>;
  if (d.kind === "email") {
    const subject = str(d.subject);
    const body = str(d.body_text);
    return subject === null || body === null ? UNREADABLE : { kind: "email", subject, body };
  }
  if (d.kind === "file") {
    const name = str(d.name);
    const mimeType = str(d.mime_type);
    const b64 = typeof d.content_b64 === "string" ? d.content_b64 : null;
    const bytes = b64 === null ? null : decodeBase64(b64);
    if (name === null || mimeType === null || bytes === null) return UNREADABLE;
    return {
      kind: "file",
      name,
      mimeType,
      bytes: bytes.length,
      text: TEXT_TYPES.test(mimeType) ? plainOrNull(textOf(bytes)) : null,
    };
  }
  if (d.kind === "calendar_event") {
    const title = str(d.title);
    const start = str(d.start);
    const end = str(d.end);
    const zone = str(d.time_zone);
    return title === null || start === null || end === null || zone === null
      ? UNREADABLE
      : { kind: "calendar_event", title, start, end, zone };
  }
  return UNREADABLE;
}
