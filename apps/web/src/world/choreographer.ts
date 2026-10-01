// HR-3 / PRD 9.7: animations queue per actor (never skip/overlap); different actors animate
// concurrently; every movement caps at 2,000ms; nothing starts before its event was received.
// Clock-injected (`advance(nowMs)`, never reads the real clock itself) so it is pure and
// unit-testable. The only code allowed to animate world objects (root CLAUDE.md).
//
// Each move is scheduled algebraically at enqueue time: start = max(receivedAtMs, the previous
// move's finish), so the rules hold however sparsely `advance` is later called.

export const MAX_DURATION_MS = 2000;

export interface QueuedMove {
  readonly actor: string;
  readonly seq: number;
  readonly receivedAtMs: number;
  readonly durationMs: number;
}

export interface Choreographer {
  enqueue(move: QueuedMove): void;
  advance(nowMs: number): void;
  isAnimating(actor: string): boolean;
  activeSeq(actor: string): number | null;
  /** The in-flight move's seq and its scheduled start..finish window, for interpolation. */
  active(actor: string): { seq: number; start: number; finish: number } | null;
  completed(actor: string): number[];
}

interface Scheduled {
  readonly move: QueuedMove;
  readonly start: number;
  readonly finish: number;
}

interface ActorState {
  schedule: Scheduled[];
  nextIndex: number; // first not-yet-completed (as of lastNow) entry in `schedule`
  lastNow: number;
  completedSeqs: number[];
  scheduleEnd: number; // finish time of the last scheduled move, for chaining the next one
}

/** `reducedMotion` may be a live getter: each enqueue reads it, so a mid-playback change applies
 * to every later movement with no restart. */
export function createChoreographer(
  opts: { reducedMotion?: boolean | (() => boolean) } = {},
): Choreographer {
  const rm = opts.reducedMotion ?? false;
  const reducedMotion = typeof rm === "function" ? rm : () => rm;
  const actors = new Map<string, ActorState>();

  const actorOf = (id: string): ActorState => {
    let a = actors.get(id);
    if (!a) {
      a = {
        schedule: [],
        nextIndex: 0,
        lastNow: Number.NEGATIVE_INFINITY,
        completedSeqs: [],
        scheduleEnd: Number.NEGATIVE_INFINITY,
      };
      actors.set(id, a);
    }
    return a;
  };

  const current = (actor: string): Scheduled | null => {
    const a = actors.get(actor);
    if (!a) return null;
    const c = a.schedule[a.nextIndex];
    return c && a.lastNow >= c.start ? c : null;
  };

  return {
    enqueue(move) {
      const a = actorOf(move.actor);
      const start = Math.max(move.receivedAtMs, a.scheduleEnd);
      const durationMs = reducedMotion() ? 0 : Math.min(move.durationMs, MAX_DURATION_MS);
      const finish = start + durationMs;
      a.schedule.push({ move, start, finish });
      a.scheduleEnd = finish;
    },
    advance(nowMs) {
      for (const a of actors.values()) {
        a.lastNow = nowMs;
        for (
          let entry = a.schedule[a.nextIndex];
          entry && entry.finish <= nowMs;
          entry = a.schedule[a.nextIndex]
        ) {
          a.completedSeqs.push(entry.move.seq);
          a.nextIndex++;
        }
      }
    },
    isAnimating(actor) {
      return current(actor) !== null;
    },
    activeSeq(actor) {
      return current(actor)?.move.seq ?? null;
    },
    active(actor) {
      const c = current(actor);
      return c ? { seq: c.move.seq, start: c.start, finish: c.finish } : null;
    },
    completed(actor) {
      return actors.get(actor)?.completedSeqs ?? [];
    },
  };
}
