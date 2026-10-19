// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { saveNamedResult, saveResult } from "./results";

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("DOCS_OUT A3 the saved file name follows its type", () => {
  it("P0_RESULTS_named_working_file_download_keeps_its_real_name", () => {
    let name = "";
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    saveNamedResult(new Blob(["notes"], { type: "text/markdown" }), "Research notes.md");
    expect(name).toBe("Research notes.md");
  });
  it.each([
    ["application/pdf", ".pdf"],
    [DOCX, ".docx"],
    [PPTX, ".pptx"],
    [XLSX, ".xlsx"],
    ["text/csv", ".csv"],
    ["text/markdown", ".md"],
    ["application/octet-stream", ""],
  ])("DOCS_OUT A3 %s saves as %s", (type, extension) => {
    let name = "";
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    saveResult(new Blob(["x"], { type }), "w_1");
    expect(click).toHaveBeenCalledOnce();
    expect(name).toBe(`tilo-result-w_1${extension}`);
  });
});
