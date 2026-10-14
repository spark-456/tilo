import { describe, expect, it, vi } from "vitest";
import { gmtLabel } from "./settingsForm";

describe("WEB-P1 time zone display label (issue 588, BQ-SETWEB-1)", () => {
  it("FR_SET_01_gmt_label_is_the_offset_of_an_iana_zone_at_a_given_date", () => {
    expect(gmtLabel("Europe/London", new Date("2026-01-15T12:00:00Z"))).toBe("GMT");
    expect(gmtLabel("Europe/London", new Date("2026-07-15T12:00:00Z"))).toBe("GMT+1");
    expect(gmtLabel("Asia/Kolkata", new Date("2026-07-15T12:00:00Z"))).toBe("GMT+5:30");
  });
  it("FR_SET_01_gmt_label_is_null_for_a_zone_the_runtime_does_not_know", () => {
    expect(gmtLabel("Not/AZone")).toBeNull();
    expect(gmtLabel("")).toBeNull();
  });
  it.each(["GMT+0", "GMT-0", "GMT+0:00"])(
    "FR_SET_01_gmt_label_normalizes_zero_offset_%s",
    (label) => {
      const formatter = vi
        .spyOn(Intl.DateTimeFormat.prototype, "formatToParts")
        .mockReturnValue([{ type: "timeZoneName", value: label }]);
      try {
        expect(gmtLabel("Europe/London", new Date("2026-01-15T12:00:00Z"))).toBe("GMT");
      } finally {
        formatter.mockRestore();
      }
    },
  );
});
