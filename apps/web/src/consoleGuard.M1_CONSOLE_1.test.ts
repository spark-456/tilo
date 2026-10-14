import { describe, expect, it, vi } from "vitest";
import { guardConsoleErrors } from "../test-support/park/consoleGuard";

describe("M1_CONSOLE_1 console failure guard", () => {
  it("records errors and forwards the original diagnostic", () => {
    const errors: unknown[][] = [];
    const output = vi.fn();
    const guarded = guardConsoleErrors(
      { ...console, error: (...args: unknown[]) => output(...args) },
      (args) => errors.push(args),
    );
    guarded.error("diagnostic", { detail: 1 });
    expect(errors).toEqual([["diagnostic", { detail: 1 }]]);
    expect(output).toHaveBeenCalledWith("diagnostic", { detail: 1 });
  });

  it("retains errors through a silent spy, clear, reset and restore", () => {
    const errors: unknown[][] = [];
    const output = vi.fn();
    const guarded = guardConsoleErrors(
      { ...console, error: (...args: unknown[]) => output(...args) },
      (args) => errors.push(args),
    );
    const spy = vi.spyOn(guarded, "error").mockImplementation(() => undefined);
    guarded.error("before clear");
    spy.mockClear();
    guarded.error("before reset");
    spy.mockReset();
    guarded.error("before restore");
    spy.mockRestore();
    guarded.error("after restore");
    expect(errors).toEqual([
      ["before clear"],
      ["before reset"],
      ["before restore"],
      ["after restore"],
    ]);
    expect(output).toHaveBeenCalledWith("after restore");
  });

  it("leaves other console methods callable without recording errors", () => {
    const record = vi.fn();
    const warn = vi.fn();
    const guarded = guardConsoleErrors({ ...console, warn }, record);
    guarded.warn("warning");
    expect(warn).toHaveBeenCalledWith("warning");
    expect(record).not.toHaveBeenCalled();
  });
});
