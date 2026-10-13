// ADR-0035 L6c (FR-CON-02): the web half of the fields route. A needs-you card that asks for fields (its option `provide`)
// is answered with values the person types, not with a tap: `GET /worlds/{id}/cards/{cid}/fields` says what is asked
// (label, hint, limit; never a value) and `POST` supplies them. Typed values go to that one POST and nowhere else.

export interface FieldSpec {
  readonly name: string;
  readonly label: string;
  readonly hint: string;
  readonly maxLength: number;
}

/** The two calls a form needs; `HttpClient` has them, the fixture client does not (nothing to supply offline). */
export interface FieldsApi {
  getCardFields(cardId: string): Promise<FieldSpec[]>;
  supplyCardFields(cardId: string, values: Readonly<Record<string, string>>): Promise<void>;
}

export const isFieldsApi = (v: unknown): v is FieldsApi =>
  typeof (v as Partial<FieldsApi> | null)?.getCardFields === "function" &&
  typeof (v as Partial<FieldsApi> | null)?.supplyCardFields === "function";

const NAME = /^[a-z][a-z_]{0,31}$/;
const MAX = 1000;

/** The asked fields of a reply, or null when it is not the documented `{fields: [{name, label, hint, max_length}]}`. */
export function fieldSpecsOf(body: unknown): FieldSpec[] | null {
  const list = (body as { fields?: unknown } | null)?.fields;
  if (!Array.isArray(list) || list.length === 0 || list.length > 8) return null;
  const out: FieldSpec[] = [];
  for (const raw of list) {
    const f = raw as Record<string, unknown> | null;
    if (!f || typeof f.name !== "string" || !NAME.test(f.name)) return null;
    const max = typeof f.max_length === "number" ? Math.floor(f.max_length) : 150;
    out.push({
      name: f.name,
      label: typeof f.label === "string" && f.label.length <= 60 ? f.label : f.name,
      hint: typeof f.hint === "string" && f.hint.length <= 200 ? f.hint : "",
      maxLength: max >= 1 && max <= MAX ? max : 150,
    });
  }
  return out;
}

/** The check made before sending: what is certain without the server (the server checks the rest and says why). */
export function fieldProblem(spec: FieldSpec, value: string): string | null {
  const text = value.trim();
  if (!text) return `${spec.label} is needed.`;
  if (text.length > spec.maxLength)
    return `${spec.label} must be at most ${spec.maxLength} characters.`;
  // biome-ignore lint/suspicious/noControlCharactersInRegex: a line break or control character is what is refused
  if (/[\u0000-\u001f\u007f\u2028\u2029]/.test(text)) return `${spec.label} must be on one line.`;
  if (
    spec.name === "recipient" &&
    !text.split(",").every((a) => /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(a.trim()))
  ) {
    return "Use plain email addresses like name@example.org, separated by commas.";
  }
  return null;
}
