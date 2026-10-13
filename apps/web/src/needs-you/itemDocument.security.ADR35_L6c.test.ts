// ADR35_L6c / FR_CON_02 security: sizes are capped before any parse or decode, and shown text has no format characters.
import { describe, expect, it } from "vitest";
import { B64_MAX, RAW_MAX, decodeItemDocument, plain } from "./itemDocument";

describe("ADR35_L6c FR_CON_02 item document limits", () => {
  it("refuses an oversize document or file before parsing or decoding", () => {
    expect(decodeItemDocument(" ".repeat(RAW_MAX + 1))).toEqual({ kind: "unreadable" });
    const huge = "QUJD".repeat(B64_MAX / 4 + 1);
    const file = JSON.stringify({
      kind: "file",
      name: "a",
      mime_type: "text/plain",
      content_b64: huge,
    });
    expect(decodeItemDocument(file)).toEqual({ kind: "unreadable" });
  });

  it("removes bidi overrides and isolates and other format characters from every shown field", () => {
    const spoof = "invoice\u202Etxt.exe\u2066x\u2069\u200b";
    expect(plain(spoof)).toBe("invoicetxt.exex");
    const mail = decodeItemDocument(
      JSON.stringify({ kind: "email", subject: spoof, body_text: `a${spoof}\nb` }),
    );
    expect(mail).toEqual({
      kind: "email",
      subject: "invoicetxt.exex",
      body: "ainvoicetxt.exex\nb",
    });
    const b64 = btoa("hi");
    const file = decodeItemDocument(
      JSON.stringify({ kind: "file", name: spoof, mime_type: "text/plain", content_b64: b64 }),
    );
    expect(file).toMatchObject({ kind: "file", name: "invoicetxt.exex", text: "hi" });
    const event = decodeItemDocument(
      JSON.stringify({
        kind: "calendar_event",
        title: spoof,
        start: "s",
        end: "e",
        time_zone: "z",
      }),
    );
    expect(event).toMatchObject({ kind: "calendar_event", title: "invoicetxt.exex" });
  });
});
