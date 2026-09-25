/**
 * P0-08b-player: HR-3 / PRD 9.7 unit tests for apps/web/src/world/choreographer.ts
 * ("A choreographer queues animations per actor so events never skip; movement durations are
 * capped"; PRD 9.7 "Reduced motion: movement becomes fades").
 *
 * Interface under test (module does not exist yet). Clock-injected, per the ticket's suggested
 * module layout ("a pure, clock-injected scheduler unit-testable without a browser"): the
 * choreographer never reads Date.now()/performance.now() itself — the caller drives it forward
 * with an explicit `advance(nowMs)`, so these tests run with no browser, no timers and no
 * requestAnimationFrame.
 *
 *   export const MAX_DURATION_MS = 2000; // HR-3: "capped at 2 s"
 *   export interface QueuedMove {
 *     actor: string;
 *     seq: number;
 *     receivedAtMs: number; // when this event was received off the stream — the choreographer
 *                            // must never animate it before this instant (HR-3: "the world
 *                            // never runs ahead of the harness")
 *     durationMs: number;   // the caller's requested duration (e.g. from path length); the
 *                            // choreographer clamps it to MAX_DURATION_MS
 *   }
 *   export interface Choreographer {
 *     enqueue(move: QueuedMove): void;
 *     advance(nowMs: number): void;         // progress to nowMs: finish due animations, and for
 *                                            // each actor start its next queued move once the
 *                                            // previous one finished and nowMs >= its receivedAtMs
 *     isAnimating(actor: string): boolean;
 *     activeSeq(actor: string): number | null; // the seq currently animating for actor, if any
 *     completed(actor: string): number[];      // seqs that finished, in completion (= seq) order
 *   }
 *   export function createChoreographer(opts?: { reducedMotion?: boolean }): Choreographer;
 *
 * Reduced motion: PRD 9.7/18.2 turn movement into an instant change or a fade — modelled here as
 * an effective duration of 0ms (the same convention apps/web/src/stage/camera.ts already uses
 * for `getCameraPanDurationMs(reducedMotion)`).
 */
import fc from "fast-check";
import { expect, test } from "vitest";
import { MAX_DURATION_MS, createChoreographer } from "./choreographer";

test("HR-3 choreographer: MAX_DURATION_MS is 2000 (PRD 9.7/9.5 'at most 2 s')", () => {
  expect(MAX_DURATION_MS).toBe(2000);
});

test("HR-3 choreographer: one actor's events animate in seq order, never skipped, never overlapping", () => {
  const c = createChoreographer();
  c.enqueue({ actor: "A_s1", seq: 10, receivedAtMs: 0, durationMs: 500 });
  c.enqueue({ actor: "A_s1", seq: 11, receivedAtMs: 100, durationMs: 500 });

  c.advance(0);
  expect(c.activeSeq("A_s1")).toBe(10);

  c.advance(499);
  expect(c.activeSeq("A_s1"), "seq 11 must not start before seq 10 finishes").toBe(10);
  expect(c.completed("A_s1")).toEqual([]);

  c.advance(500);
  expect(c.completed("A_s1")).toEqual([10]);
  expect(
    c.activeSeq("A_s1"),
    "seq 11 must start as soon as seq 10 finishes and it was received",
  ).toBe(11);

  c.advance(999);
  expect(c.activeSeq("A_s1")).toBe(11);

  c.advance(1000);
  expect(c.completed("A_s1")).toEqual([10, 11]);
  expect(c.isAnimating("A_s1")).toBe(false);
});

test("HR-3 choreographer: different actors animate concurrently", () => {
  const c = createChoreographer();
  c.enqueue({ actor: "A_s1", seq: 1, receivedAtMs: 0, durationMs: 500 });
  c.enqueue({ actor: "A_s2", seq: 2, receivedAtMs: 0, durationMs: 500 });

  c.advance(250);
  expect(c.isAnimating("A_s1")).toBe(true);
  expect(c.isAnimating("A_s2")).toBe(true);
});

test("HR-3 choreographer: a move lasts at most 2,000 ms however long the requested path/duration", () => {
  const c = createChoreographer();
  c.enqueue({ actor: "A_s1", seq: 1, receivedAtMs: 0, durationMs: 10_000 });

  c.advance(1999);
  expect(c.isAnimating("A_s1"), "still animating just before the 2s cap").toBe(true);

  c.advance(2000);
  expect(c.isAnimating("A_s1"), "must be capped at 2000ms even though 10000ms was requested").toBe(
    false,
  );
  expect(c.completed("A_s1")).toEqual([1]);
});

test("HR-3 choreographer: an animation never starts before its event was received (the world never runs ahead of the stream)", () => {
  const c = createChoreographer();
  c.enqueue({ actor: "A_s1", seq: 1, receivedAtMs: 500, durationMs: 200 });

  c.advance(100);
  expect(c.isAnimating("A_s1"), "must not animate before receivedAtMs").toBe(false);
  expect(c.activeSeq("A_s1")).toBeNull();

  c.advance(500);
  expect(c.isAnimating("A_s1")).toBe(true);
});

test("PRD-9.7/18.2 choreographer: reduced motion makes movement an instant change (0ms), not a timed animation", () => {
  const c = createChoreographer({ reducedMotion: true });
  c.enqueue({ actor: "A_s1", seq: 1, receivedAtMs: 0, durationMs: 800 });

  c.advance(0);
  expect(c.isAnimating("A_s1"), "reduced motion must not run an 800ms animation").toBe(false);
  expect(c.completed("A_s1")).toEqual([1]);
});

test("HR-3 choreographer property: a single actor's events always complete in strict seq order, never overlapping", () => {
  fc.assert(
    fc.property(
      fc.array(
        fc.record({
          receivedAtMs: fc.integer({ min: 0, max: 5000 }),
          durationMs: fc.integer({ min: 1, max: 3000 }),
        }),
        { minLength: 1, maxLength: 15 },
      ),
      (rows) => {
        const c = createChoreographer();
        // seq must be assigned in ascending order of receipt for this property to make sense,
        // matching a real stream where seq is strictly increasing per world (PRD 9.3).
        const sorted = [...rows].sort((a, b) => a.receivedAtMs - b.receivedAtMs);
        sorted.forEach((row, i) => c.enqueue({ actor: "A_s1", seq: i + 1, ...row }));

        const maxReceived = Math.max(...sorted.map((r) => r.receivedAtMs));
        const horizon = maxReceived + MAX_DURATION_MS * sorted.length + 10;
        for (let t = 0; t <= horizon; t += 10) c.advance(t);

        const done = c.completed("A_s1");
        expect(done).toEqual(sorted.map((_, i) => i + 1)); // every seq, in order, none skipped
      },
    ),
    { numRuns: 25 },
  );
});
