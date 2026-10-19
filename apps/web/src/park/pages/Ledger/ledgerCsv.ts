// FR-SPD-08 Month export: the Ledger's month as a CSV. Pure functions, no clock, no network.
// The rows are the Activity rows the page shows (`activityGroups`, every type, decisions already taken
// included), in the order the page shows them, so the file and the page agree in count and in total.
// Format: RFC 4180 (CRLF line ends, a header row, cells quoted when they hold a comma, quote or line break).
// Amount: a plain decimal in the Ledger's own currency, with no symbol and no thousands separator, blank when
// the row shows no money; the Currency column names the currency (GBP unless the Ledger says USD).
// Formula guard: a text cell that starts with = + - @ tab or CR gets a leading single quote, so a
// spreadsheet reads it as text. Nothing is exported that the row does not show (no world id, no decision key).
import type { Dec, Decision, Ledger, Source } from "../../api/types";
import { activityGroups } from "./model";

export const CSV_COLUMNS = [
  "Date",
  "Time",
  "Type",
  "Entry",
  "Where",
  "Amount",
  "Currency",
  "Details",
] as const;

const NEEDS_QUOTES = /[",\r\n]/;
const FORMULA_LEAD = /^(?:\s*[=+\-@]|[\t\r])/;

/** One cell: guarded against spreadsheet formulas, then quoted when RFC 4180 requires it. */
export function csvCell(value: string): string {
  const text = FORMULA_LEAD.test(value) ? `'${value}` : value;
  return NEEDS_QUOTES.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** The money a row shows as a plain decimal: the digits and the point, no symbol, comma or sign ("—" gives nothing). */
const amountOf = (shown: string): string =>
  /\d[\d,]*(?:\.\d+)?/.exec(shown)?.[0].replaceAll(",", "") ?? "";

export function ledgerCsv(L: Ledger, dec: Dec, decisions: readonly Decision[] = []): string {
  const currency = L.currency ?? "GBP";
  const rows = activityGroups(L, dec, "all", decisions).groups.flatMap((g) =>
    g.rows.map((r) => [
      g.day,
      r.time,
      r.tag,
      r.what,
      r.sub,
      amountOf(r.amt),
      currency,
      r.detail.map((d) => `${d.k}: ${d.v}`).join("; "),
    ]),
  );
  return [[...CSV_COLUMNS], ...rows].map((r) => `${r.map(csvCell).join(",")}\r\n`).join("");
}

/**
 * The file name: `tilo-ledger-<month>-<year>.csv`. Anything but live data says `sample`, so a file made from
 * the sample Ledger can never pass for a real month (HR-1..HR-7).
 */
export function ledgerCsvFileName(month: { label: string }, source: Source | undefined): string {
  const slug = month.label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
  return `tilo-ledger-${slug}${source === "live" ? "" : "-sample"}.csv`;
}
