import { TiloApiError } from "../../../api/http";
import type { AgendaPlateRow, LiveAgenda } from "../types";

/** Keep the server's calendar-entry discriminator at the mapping boundary. */
export const isCalendarEntry = (item: AgendaPlateRow): boolean =>
  item.ref.kind === "calendar_entry";

const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string";
const nullable = (v: unknown): v is string | null => v === null || text(v);
const row = (v: unknown): v is AgendaPlateRow =>
  object(v) &&
  object(v.ref) &&
  text(v.ref.kind) &&
  text(v.ref.id) &&
  nullable(v.title) &&
  nullable(v.due) &&
  nullable(v.at) &&
  nullable(v.from) &&
  text(v.group);

/** No fixture defaults: unserved fields stay null, server rows keep their order and facts. */
export function agendaFromPlate(v: unknown): LiveAgenda {
  if (
    !object(v) ||
    !text(v.today) ||
    !text(v.as_of) ||
    typeof v.truncated !== "boolean" ||
    !Array.isArray(v.rows) ||
    !v.rows.every(row) ||
    !Array.isArray(v.parked) ||
    !v.parked.every(row)
  )
    throw new TiloApiError("Tilo sent an Agenda reply this page could not read.", 200, true);
  const rows = (items: AgendaPlateRow[]) =>
    items.map((r) => ({
      ref: { ...r.ref },
      title: r.title,
      due: r.due,
      at: r.at,
      from: r.from,
      group: r.group,
    }));
  return {
    days: null,
    wkend: null,
    today: null,
    start: null,
    end: null,
    now: null,
    events: null,
    slots: null,
    details: null,
    pins: null,
    rules: null,
    plate: {
      today: v.today,
      asOf: v.as_of,
      rows: rows(v.rows),
      parked: rows(v.parked),
      truncated: v.truncated,
    },
  };
}
