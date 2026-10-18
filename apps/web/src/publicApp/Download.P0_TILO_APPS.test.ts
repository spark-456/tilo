// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { saveResult } from "../park/api/results";

afterEach(() => vi.restoreAllMocks());

it("P0-TILO-APPS downloads a charset-qualified CSV as .csv", () => {
  vi.stubGlobal("URL", { createObjectURL: () => "blob:test", revokeObjectURL: () => undefined });
  let name = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    name = this.download;
  });
  saveResult(new Blob(["answer\nyes"], { type: "text/csv; charset=utf-8" }), "Survey responses");
  expect(name).toMatch(/\.csv$/);
});
