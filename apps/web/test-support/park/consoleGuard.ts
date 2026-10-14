import { format } from "node:util";
import { beforeEach, expect, onTestFinished } from "vitest";

export function guardConsoleErrors(original: Console, record: (args: unknown[]) => void): Console {
  const wrappers = new WeakMap<typeof console.error, typeof console.error>();
  // Intercept the call, including when a test replaces error with a restored or
  // silent spy. Forward the call and its mock metadata; never hide diagnostics.
  return new Proxy(original, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver);
      if (property !== "error" || typeof value !== "function") return value;
      let wrapped = wrappers.get(value);
      if (!wrapped) {
        const guarded: typeof console.error = new Proxy(value, {
          apply(fn, thisArg, args) {
            record(args);
            return Reflect.apply(fn, thisArg, args);
          },
        });
        wrappers.set(value, guarded);
        wrapped = guarded;
      }
      return wrapped;
    },
  });
}

beforeEach(() => {
  if (!expect.getState().testPath?.replaceAll("\\", "/").includes("/src/park/")) return;
  const errors: unknown[][] = [];
  const rejections: unknown[] = [];
  const original = globalThis.console;
  globalThis.console = guardConsoleErrors(original, (args) => errors.push(args));
  const rejected = (reason: unknown) => rejections.push(reason);
  process.on("unhandledRejection", rejected);
  // This runs after page cleanup, so errors from unmount are covered too.
  onTestFinished(() => {
    globalThis.console = original;
    process.off("unhandledRejection", rejected);
    expect(
      errors,
      `Park console.error: ${errors.map((args) => format(...args)).join("\n")}`,
    ).toEqual([]);
    expect(rejections, "Park tests must not leave an unhandled rejection").toEqual([]);
  });
});
