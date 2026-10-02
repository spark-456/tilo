import { describe, expect, it } from "vitest";
import {
  MAX_BYTES,
  MAX_FILES,
  MAX_TEXT,
  checkIntake,
  clipText,
  codePoints,
  fileStatuses,
} from "./intakeRules";

const MB = 1024 * 1024;
const file = (name: string, size = 1) => ({ name, size });
const files = (n: number) => Array.from({ length: n }, (_, i) => file(`f${i}.pdf`));

describe("FR-INT-01 S-01: intake limits, with the server's wording", () => {
  it("FR-INT-01 S-01: rejects the 4,001st character, an 11th file, 50 MB plus one byte, and an unsupported type, each with its exact message", () => {
    expect(checkIntake("x".repeat(MAX_TEXT + 1), [])).toBe(
      "The text is 4001 characters; the limit is 4000.",
    );
    expect(checkIntake("task", files(MAX_FILES + 1))).toBe("11 files attached; the limit is 10.");
    expect(checkIntake("task", [file("big.pdf", MAX_BYTES + 1)])).toBe(
      "The files total more than 50 MB.",
    );
    expect(checkIntake("task", [file("notes.txt")])).toBe(
      "notes.txt is not accepted; attach PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG files.",
    );
  });

  it("FR-INT-01 S-01: the limits themselves are accepted, and every listed type with any letter case", () => {
    expect(checkIntake("x".repeat(MAX_TEXT), [])).toBeNull();
    expect(checkIntake("task", files(MAX_FILES))).toBeNull();
    expect(checkIntake("task", [file("a.pdf", 25 * MB), file("b.csv", 25 * MB)])).toBeNull();
    const names = ["a.PDF", "b.docx", "c.pptx", "d.xlsx", "e.csv", "f.png", "g.JPG", "h.jpeg"];
    expect(
      checkIntake(
        "task",
        names.map((n) => file(n)),
      ),
    ).toBeNull();
  });

  it("FR-INT-01 S-01: the server's check order holds, and a long file name is clipped to 80", () => {
    expect(checkIntake("  ", [])).toBe("Describe the task in text.");
    expect(checkIntake("x".repeat(MAX_TEXT + 1), files(11))).toMatch(/^The text is/);
    expect(checkIntake("task", [...files(10), file("z.txt")])).toBe(
      "11 files attached; the limit is 10.",
    );
    const long = `${"n".repeat(90)}.txt`;
    expect(checkIntake("task", [file(long)])).toBe(
      `${"n".repeat(79)}… is not accepted; attach PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG files.`,
    );
  });

  it("FR-INT-01 S-01: the text limit counts code points, as the server's len() does, and clipping never splits a pair", () => {
    expect(codePoints("a😀b")).toBe(3);
    expect(checkIntake("😀".repeat(MAX_TEXT), [])).toBeNull(); // 8,000 UTF-16 units
    expect(checkIntake("😀".repeat(MAX_TEXT + 1), [])).toBe(
      "The text is 4001 characters; the limit is 4000.",
    );
    const clipped = clipText(`${"😀".repeat(MAX_TEXT)}😀`);
    expect(Array.from(clipped)).toHaveLength(MAX_TEXT);
    expect(clipped.endsWith("😀")).toBe(true);
    expect(clipText("short")).toBe("short");
  });

  it("FR-INT-01 S-01: each file's status reflects the type, the file count and the total size", () => {
    expect(fileStatuses([file("a.pdf"), file("b.txt")])).toEqual(["Ready to send", "Not accepted"]);
    expect(fileStatuses(files(12)).slice(9)).toEqual([
      "Ready to send",
      "Over the 10 file limit",
      "Over the 10 file limit",
    ]);
    const sizes = [file("a.pdf", 50 * MB), file("b.pdf", 1), file("c.pdf", 1)];
    expect(fileStatuses(sizes)).toEqual([
      "Ready to send",
      "Over the 50 MB total",
      "Over the 50 MB total",
    ]);
    expect(fileStatuses([])).toEqual([]);
  });
});
