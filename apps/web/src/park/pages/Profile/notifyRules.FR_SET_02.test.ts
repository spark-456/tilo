// FR-SET-02 (AGY-WEB-4): the pure notification rules. Decisions always keep at least one channel, and
// quiet hours never hide a gate: a gate that cannot be pushed during quiet hours waits in "Needs you".
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { canSwitchOff, isGate, reachDuringQuiet } from "./notifyRules";

const EVENTS = ["decisions", "spend", "finished", "digest", "weekly"] as const;
const row = fc.tuple(fc.boolean(), fc.boolean(), fc.boolean());

describe("FR_SET_02_notify_rules", () => {
  it("test_FR_SET_02_only_the_decisions_event_is_a_gate", () => {
    expect(EVENTS.filter(isGate)).toEqual(["decisions"]);
  });

  it("test_FR_SET_02_the_last_channel_of_decisions_cannot_be_switched_off", () => {
    expect(canSwitchOff("decisions", [true, false, false], 0)).toBe(false);
    expect(canSwitchOff("decisions", [true, true, false], 0)).toBe(true);
    expect(canSwitchOff("decisions", [false, false, true], 2)).toBe(false);
    expect(canSwitchOff("spend", [true, false, false], 0), "other events may go silent").toBe(true);
  });

  it("test_FR_SET_02_property_turning_channels_off_never_empties_decisions", () => {
    fc.assert(
      fc.property(fc.array(fc.integer({ min: 0, max: 2 }), { maxLength: 30 }), (clicks) => {
        let cells = [true, true, true];
        for (const c of clicks) {
          const next = cells[c] === true ? !canSwitchOff("decisions", cells, c) : true;
          cells = cells.map((v, i) => (i === c ? next : v));
          expect(cells.some(Boolean)).toBe(true);
        }
      }),
    );
  });

  it("test_FR_SET_02_quiet_hours_silence_the_phone_but_not_email_or_slack", () => {
    const base = { id: "spend", quietOn: true, overThreshold: false } as const;
    expect(reachDuringQuiet({ ...base, channels: [true, false, false] })).toBe("waiting");
    expect(reachDuringQuiet({ ...base, channels: [true, true, false] })).toBe("pushed");
    expect(reachDuringQuiet({ ...base, channels: [false, false, false] })).toBe("off");
    expect(reachDuringQuiet({ ...base, quietOn: false, channels: [true, false, false] })).toBe(
      "pushed",
    );
  });

  it("test_FR_SET_02_a_decision_over_the_threshold_reaches_the_phone_during_quiet_hours", () => {
    expect(
      reachDuringQuiet({
        id: "decisions",
        quietOn: true,
        overThreshold: true,
        channels: [true, false, false],
      }),
    ).toBe("pushed");
  });

  it("test_FR_SET_02_property_quiet_hours_never_hide_a_gate", () => {
    fc.assert(
      fc.property(row, fc.boolean(), fc.boolean(), (channels, quietOn, overThreshold) => {
        const r = reachDuringQuiet({ id: "decisions", channels, quietOn, overThreshold });
        // A gate is pushed now or waits in Needs you; it is never "off" and never silently dropped.
        expect(r === "pushed" || r === "waiting").toBe(true);
      }),
    );
  });

  it("test_FR_SET_02_property_with_quiet_hours_off_any_enabled_channel_pushes", () => {
    fc.assert(
      fc.property(fc.constantFrom(...EVENTS), row, fc.boolean(), (id, channels, over) => {
        const r = reachDuringQuiet({ id, channels, quietOn: false, overThreshold: over });
        expect(r === "pushed").toBe(channels.some(Boolean));
      }),
    );
  });
});
