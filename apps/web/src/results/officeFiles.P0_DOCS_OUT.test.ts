// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { inflateRawSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { previewDocx, previewXlsx } from "./officeFiles";

const file = (name: string, type: string): Blob =>
  new Blob([readFileSync(resolve(process.cwd(), "src/results/fixtures", name))], { type });
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const inflate = async (data: Uint8Array) => new Uint8Array(inflateRawSync(data));

describe("P0_DOCS_OUT office previews", () => {
  it("P0_DOCS_OUT_xlsx_preview_shows_the_first_sheet_with_typed_cells_and_computed_values", async () => {
    const summary = await previewXlsx(file("sales.xlsx", XLSX), 0, inflate);
    expect(summary.sheets).toEqual(["Summary", "Summary 2"]); // the report text first, then the table
    expect(summary.rows[0]).toEqual(["Q3 Sales Review"]);
    const view = await previewXlsx(file("sales.xlsx", XLSX), 1, inflate);
    expect(view.rows[0]).toEqual(["Region", "Closed on", "Units", "Unit price", "Revenue"]);
    expect(view.rows[1]).toEqual(["North", "2026-09-30", "3", "10.5", "31.5"]);
    expect(view.rows[2]?.[4]).toBe("81");
    expect(view.rows[4]).toEqual(["Total", "", "12", "38.75", "152.5"]);
    expect(view.moreRows).toBe(false);
  });

  it("P0_DOCS_OUT_docx_preview_keeps_headings_bullets_and_tables_in_order", async () => {
    const view = await previewDocx(file("sales.docx", DOCX), inflate);
    const kinds = view.blocks.map((b) => b.kind);
    expect(kinds.slice(0, 5)).toEqual(["title", "subtitle", "subtitle", "h1", "p"]);
    expect(view.blocks[0]).toEqual({ kind: "title", text: "Q3 Sales Review" });
    expect(view.blocks.filter((b) => b.kind === "li")).toHaveLength(2);
    const table = view.blocks.find((b) => b.kind === "table");
    expect(table && "rows" in table ? table.rows[0] : []).toEqual([
      "Region",
      "Closed on",
      "Units",
      "Unit price",
      "Revenue",
    ]);
    expect(view.blocks.some((b) => b.kind === "h1" && "text" in b && b.text === "Next steps")).toBe(
      true,
    );
  });

  it("P0_DOCS_OUT_preview_refuses_a_file_that_is_not_a_zip_package", async () => {
    await expect(previewDocx(new Blob(["plain text, not a zip"]), inflate)).rejects.toThrow();
    await expect(previewXlsx(new Blob(["plain text, not a zip"]), 0, inflate)).rejects.toThrow();
  });

  it("P0_DOCS_OUT_browser_inflate_reads_the_same_files", async () => {
    if (typeof DecompressionStream === "undefined") return; // older runtimes: the node inflate above covers parsing
    const view = await previewXlsx(file("sales.xlsx", XLSX), 1);
    expect(view.rows[0]?.[0]).toBe("Region");
  });
});
