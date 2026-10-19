import { describe, expect, it } from "vitest";
import { ACCEPTED, ACCEPT_ATTR, isAccepted } from "./uploadRules";

describe("FR-INT-01 upload rules: file types", () => {
  it("FR_INT_01_text_markdown_and_json_files_are_accepted_with_the_other_types", () => {
    for (const name of [
      "notes.txt",
      "README.md",
      "data.json",
      "NOTES.TXT",
      "a.csv",
      "q.docx",
      "s.pdf",
      "p.jpeg",
    ]) {
      expect(isAccepted(name), name).toBe(true);
    }
  });

  it("FR_INT_01_other_types_and_bare_extensions_are_still_refused", () => {
    for (const name of ["run.exe", "page.html", "memo.rtf", "voice.mp3", ".txt", "txt"]) {
      expect(isAccepted(name), name).toBe(false);
    }
  });

  it("FR_INT_01_the_picker_filter_and_the_sentence_name_the_same_types", () => {
    expect(ACCEPT_ATTR.split(",")).toEqual(expect.arrayContaining([".txt", ".md", ".json"]));
    expect(ACCEPTED).toContain("TXT, MD, JSON");
  });
});
