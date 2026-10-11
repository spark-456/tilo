export const PLATE_GROUPS = {
  attention: "Needs attention",
  overdue: "Overdue",
  soon: "Due soon",
  rest: "The rest",
  snoozed: "Snoozed",
  asked: "Asked to be reassigned",
  done: "Done",
} as const;
type Group = keyof typeof PLATE_GROUPS;
interface Row {
  key: string;
  group: Group;
  title: string | null;
  due: string | null;
  at: string | null;
}
export interface PlateView {
  asOf: string;
  truncated: boolean;
  rows: Row[];
}
const optionalText = (v: unknown): v is string | null => v === null || typeof v === "string";

/** FR-PA-02/03: the complete served plate, without fixture identity, local grouping or invented facts. */
export function plateFromReply(body: unknown): PlateView | null {
  if (
    !body ||
    typeof body !== "object" ||
    !("rows" in body) ||
    !Array.isArray(body.rows) ||
    !("parked" in body) ||
    !Array.isArray(body.parked) ||
    !("as_of" in body) ||
    typeof body.as_of !== "string" ||
    !("truncated" in body) ||
    typeof body.truncated !== "boolean"
  )
    return null;
  const rows: Row[] = [];
  for (const r of [...body.rows, ...body.parked]) {
    if (
      !r ||
      typeof r !== "object" ||
      !r.ref ||
      typeof r.ref !== "object" ||
      typeof r.ref.kind !== "string" ||
      typeof r.ref.id !== "string" ||
      typeof r.group !== "string" ||
      !Object.hasOwn(PLATE_GROUPS, r.group) ||
      !optionalText(r.title) ||
      !optionalText(r.due) ||
      !optionalText(r.at)
    )
      return null;
    rows.push({
      key: `${r.ref.kind}:${r.ref.id}`,
      group: r.group as Group,
      title: r.title,
      due: r.due,
      at: r.at,
    });
  }
  return { asOf: body.as_of, truncated: body.truncated, rows };
}
