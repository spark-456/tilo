// @vitest-environment happy-dom
// FR-SPD-08 (Month export): the Ledger's month as a CSV whose rows are the Activity rows the page shows.
// A tiny RFC 4180 reader below is the test's own oracle; the page rows come from activityGroups (the model the
// Activity card renders), so "same count, same totals" is checked against what the person sees.
import { afterEach, describe, expect, it, vi } from "vitest";
import { decisions, ledger } from "../../api/fixtures";
import type { Ledger } from "../../api/types";
import { downloadCsv } from "./downloadCsv";
import { CSV_COLUMNS, csvCell, ledgerCsv, ledgerCsvFileName } from "./ledgerCsv";
import { activityGroups } from "./model";

/** RFC 4180 reader: quoted cells may hold commas, doubled quotes and line breaks; rows end in CRLF or LF. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i] as string;
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\r" || c === "\n") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

const col = (name: (typeof CSV_COLUMNS)[number]): number => CSV_COLUMNS.indexOf(name);
const MONTH = { label: "September 2026" };
/** The sum of the money a row shows ("£3,420" -> 3420, "+£2.20" -> 2.2, "—" -> nothing), worked out here. */
const shown = (amt: string): number => {
  const m = /\d[\d,]*(?:\.\d+)?/.exec(amt);
  return m ? Number(m[0].replaceAll(",", "")) : 0;
};

describe("FR_SPD_08_ledger_csv_matches_the_ledger", () => {
  it("FR_SPD_08_csv_rows_equal_the_ledger_rows_of_the_month", () => {
    const pageRows = activityGroups(ledger, {}, "all", decisions).groups.flatMap((g) => g.rows);
    const [header, ...body] = parseCsv(ledgerCsv(ledger, {}, decisions));
    expect(header).toEqual([...CSV_COLUMNS]);
    expect(body.length).toBe(pageRows.length);
    expect(body.length).toBeGreaterThan(5);
    body.forEach((r, i) => {
      const p = pageRows[i];
      expect(r[col("Time")]).toBe(p?.time);
      expect(r[col("Type")]).toBe(p?.tag);
      expect(r[col("Entry")]).toBe(p?.what);
      expect(r[col("Where")]).toBe(p?.sub);
    });
    const csvTotal = body.reduce((a, r) => a + Number(r[col("Amount")] || 0), 0);
    expect(csvTotal).toBeCloseTo(
      pageRows.reduce((a, r) => a + shown(r.amt), 0),
      6,
    );
    expect(new Set(body.map((r) => r[col("Date")]))).toEqual(
      new Set(activityGroups(ledger, {}, "all", decisions).groups.map((g) => g.day)),
    );
  });

  it("FR_SPD_08_a_decision_taken_appears_in_the_file_as_it_does_on_the_page", () => {
    const dec = { depot: true, mail: true };
    const page = activityGroups(ledger, dec, "all", decisions).groups.flatMap((g) => g.rows);
    const body = parseCsv(ledgerCsv(ledger, dec, decisions)).slice(1);
    expect(body.length).toBe(page.length);
    expect(body.map((r) => r[col("Entry")])).toEqual(page.map((r) => r.what));
    expect(body.some((r) => r[col("Time")] === "Just now")).toBe(true);
  });

  it("FR_SPD_08_has_a_header_row_in_a_stable_column_order", () => {
    expect(CSV_COLUMNS).toEqual([
      "Date",
      "Time",
      "Type",
      "Entry",
      "Where",
      "Amount",
      "Currency",
      "Details",
    ]);
    const text = ledgerCsv(ledger, {}, decisions);
    expect(text.split("\r\n")[0]).toBe(CSV_COLUMNS.join(","));
    expect(text.endsWith("\r\n")).toBe(true);
    expect(ledgerCsv(ledger, {}, decisions)).toBe(text);
  });

  it("FR_SPD_08_amounts_are_plain_decimals_in_the_ledgers_own_currency", () => {
    const body = parseCsv(ledgerCsv(ledger, {}, decisions)).slice(1);
    for (const r of body) {
      expect(r[col("Amount")]).toMatch(/^(\d+(\.\d+)?)?$/); // no symbol, no thousands separator, blank when none
      expect(r[col("Currency")]).toBe("GBP");
    }
    expect(
      body.find((r) => r[col("Entry")] === "Laptop Depot asked for sign-off")?.[col("Amount")],
    ).toBe("3420");
    expect(
      body.find((r) => r[col("Entry")] === "Supplier brief waiting at the Mail Room gate")?.[
        col("Amount")
      ],
    ).toBe("");
    const usd: Ledger = { ...ledger, currency: "USD" };
    expect(parseCsv(ledgerCsv(usd, {}, decisions))[1]?.[col("Currency")]).toBe("USD");
  });

  it("FR_SPD_08_shows_only_what_the_row_shows_no_world_id_or_decision_key", () => {
    const text = ledgerCsv(ledger, {}, decisions);
    expect(CSV_COLUMNS.join(" ").toLowerCase()).not.toMatch(/\bid\b|key|world/);
    // The fixture row `world` ids and decision keys are not columns: "depot" appears only inside shown words.
    const body = parseCsv(text).slice(1);
    for (const r of body) {
      expect(r).toHaveLength(CSV_COLUMNS.length);
      expect(r.includes("k1")).toBe(false);
      expect(r.includes("depot")).toBe(false);
    }
  });

  it("FR_SPD_08_a_ledger_with_no_rows_is_just_the_header", () => {
    const empty: Ledger = { ...ledger, activity: [] };
    expect(ledgerCsv(empty, {}, [])).toBe(`${CSV_COLUMNS.join(",")}\r\n`);
  });
});

describe("FR_SPD_08_csv_escaping_and_injection_guard", () => {
  it("FR_SPD_08_commas_quotes_and_newlines_are_quoted_per_rfc_4180", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("line1\nline2")).toBe('"line1\nline2"');
    expect(csvCell("line1\r\nline2")).toBe('"line1\r\nline2"');
  });

  it("FR_SPD_08_awkward_text_survives_a_round_trip_through_the_file", () => {
    const awkward: Ledger = {
      ...ledger,
      activity: [
        {
          day: "Mon 1 Sep",
          t: "09:00",
          k: "spend",
          world: "k1",
          what: 'Supplier "Voltcell", batch 2\nsecond line',
          sub: "A, B · C",
          amt: "£1,140",
          detail: [
            ["Note", 'has "quotes", commas'],
            ["Other", "x"],
          ],
        },
      ],
    };
    const [, row, ...rest] = parseCsv(ledgerCsv(awkward, {}, []));
    expect(rest).toEqual([]);
    expect(row?.[col("Entry")]).toBe('Supplier "Voltcell", batch 2\nsecond line');
    expect(row?.[col("Where")]).toBe("A, B · C");
    expect(row?.[col("Amount")]).toBe("1140");
    expect(row?.[col("Details")]).toBe('Note: has "quotes", commas; Other: x');
  });

  it.each(["=", "+", "-", "@", "\t", "\r"])(
    "FR_SPD_08_a_cell_starting_with_%j_is_prefixed_with_a_single_quote",
    (lead) => {
      const out = csvCell(`${lead}SUM(A1:A9)`);
      const cell = parseCsv(out)[0]?.[0];
      expect(cell).toBe(`'${lead}SUM(A1:A9)`);
    },
  );

  it("FR_SPD_08_formula_text_in_a_ledger_row_cannot_reach_the_file_as_a_formula", () => {
    const hostile: Ledger = {
      ...ledger,
      activity: [
        {
          day: "Mon 1 Sep",
          t: "09:00",
          k: "spend",
          world: "k1",
          what: '=HYPERLINK("http://x","y")',
          sub: "+1+1",
          amt: "—",
          detail: [["-2", "@cmd"]],
        },
      ],
    };
    const row = parseCsv(ledgerCsv(hostile, {}, []))[1] ?? [];
    for (const cell of row) expect(cell).not.toMatch(/^[=+\-@\t\r]/);
    expect(row[col("Entry")]).toBe(`'=HYPERLINK("http://x","y")`);
    expect(row[col("Where")]).toBe("'+1+1");
  });

  it("FR_SPD_08_text_that_only_contains_a_trigger_character_later_is_left_alone", () => {
    expect(csvCell("a=b")).toBe("a=b");
    expect(csvCell("Jin - approver")).toBe("Jin - approver");
  });
});

describe("FR_SPD_08_file_name_says_when_the_data_is_a_sample", () => {
  it("FR_SPD_08_live_data_gets_the_month_in_the_name", () => {
    expect(ledgerCsvFileName(MONTH, "live")).toBe("tilo-ledger-september-2026.csv");
  });

  it("FR_SPD_08_fixture_data_is_named_sample", () => {
    expect(ledgerCsvFileName(MONTH, "fixture")).toBe("tilo-ledger-september-2026-sample.csv");
  });

  it("FR_SPD_08_an_unknown_source_is_not_called_live", () => {
    expect(ledgerCsvFileName(MONTH, undefined)).toContain("sample");
  });

  it("FR_SPD_08_the_name_follows_the_month_chosen", () => {
    expect(ledgerCsvFileName({ label: "August 2026" }, "live")).toBe("tilo-ledger-august-2026.csv");
  });
});

describe("FR_SPD_08_download_is_a_real_blob_through_an_anchor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("FR_SPD_08_downloads_a_csv_blob_and_revokes_the_object_url", async () => {
    const blobs: Blob[] = [];
    const create = vi.fn((b: Blob) => {
      blobs.push(b);
      return "blob:tilo-test-1";
    });
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const clicked: { href: string; download: string; inDom: boolean }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ href: this.href, download: this.download, inDom: this.isConnected });
    });

    downloadCsv("tilo-ledger-september-2026-sample.csv", "A,B\r\n1,2\r\n");

    expect(create).toHaveBeenCalledTimes(1);
    expect(blobs[0]?.type).toMatch(/^text\/csv/);
    expect(await blobs[0]?.text()).toContain("A,B\r\n1,2\r\n");
    expect(clicked).toEqual([
      { href: "blob:tilo-test-1", download: "tilo-ledger-september-2026-sample.csv", inDom: true },
    ]);
    expect(revoke).toHaveBeenCalledWith("blob:tilo-test-1");
    expect(document.querySelector("a[download]")).toBeNull(); // the anchor does not stay on the page
  });
});
