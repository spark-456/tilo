import { describe, expect, it } from "vitest";
import { type LegalDoc, PRIVACY, TERMS } from "./content";

const section = (doc: LegalDoc, id: string) =>
  doc.sections
    .find((s) => s.id === id)
    ?.blocks.flatMap((b) => ("p" in b ? [b.p] : b.ul))
    .map((p) => p.map((v) => (typeof v === "string" ? v : v.text)).join(""))
    .join(" ") ?? "";

describe("WEB_LEGAL audited claims", () => {
  it("WEB_LEGAL distinguishes configured models from verified deployment", () => {
    expect(section(PRIVACY, "use")).toContain(
      "have not verified the model routing in a deployed service",
    );
    expect(section(PRIVACY, "use")).not.toContain(
      "The models that read your content are Google's Gemini",
    );
  });
  it("WEB_LEGAL limits the cache claim and discloses recordings and analytics uncertainty", () => {
    const text = section(PRIVACY, "use");
    expect(text).toContain("result cache excludes email bodies");
    expect(text).toContain("Test recordings can include message content");
    expect(text).toContain(
      "have not verified that all analytics and logs exclude message or file content",
    );
  });
  it("WEB_LEGAL states retention targets without promising enforcement", () => {
    const text = section(PRIVACY, "storage");
    expect(text).toContain("retention targets for saved data");
    expect(text).toContain("90 days");
    expect(text).toContain("30 days");
    expect(text).toContain("1 year");
    expect(text).toContain("have not verified automatic deletion across all stores");
  });
  it("WEB_LEGAL does not promise a working export or universal deletion deadline", () => {
    const text = section(PRIVACY, "controls");
    expect(text).toContain("In-app export and deletion are not available yet");
    expect(text).toContain("cannot yet guarantee deletion from every store within 30 days");
    expect(text).not.toContain("We remove it from every store within 30 days");
  });
  it("WEB_LEGAL labels human access controls as unverified", () => {
    expect(section(PRIVACY, "google")).toContain(
      "have not verified all logging paths or staff access controls",
    );
  });
  it("WEB_LEGAL does not present unreviewed liability terms as established", () => {
    expect(section(TERMS, "liability")).toContain(
      "enforceability and governing law have not been established",
    );
    expect(section(TERMS, "liability")).not.toContain("our total liability is limited");
  });
});
