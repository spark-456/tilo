// FR-WLD-04 / PRD 9.6: "Replay: scrub any finished run; the reducer is deterministic and
// snapshots every 250 events." Snapshots are immutable — later apply() calls build a new state
// object (reducer.ts already never mutates in place) and never touch an already-taken snapshot.
//
// FR-WLD-08: the Trace rows are the only part of a state that grows with the run, and appending to
// a reducer state copies them, which made building a store O(n^2) (4 s at 20,000 events). The store
// therefore folds events with an empty trace and keeps the rows in one array of its own; a snapshot
// copies the rows once (every SNAPSHOT_EVERY events), and stateAt(seq) is the nearest checkpoint
// plus the rows of the events after it. The result equals reduce(layout, events up to seq).
import type { Event, Layout } from "@tilo/contracts";
import { type WorldState, applyEvent, createInitialState } from "./reducer";

export const SNAPSHOT_EVERY = 250;

export interface WorldStore {
  apply(event: Event): void;
  stateAt(seq: number): WorldState;
  snapshotSeqs(): number[];
  currentSeq(): number;
}

export function createWorldStore(layout: Layout): WorldStore {
  const events: Event[] = [];
  // snapshots[0] is always the seq-0 initial state; every SNAPSHOT_EVERYth seq after that adds
  // one more. A plain array is fine: entries are only ever appended, never rewritten.
  const snapshots: WorldState[] = [createInitialState(layout)];
  const rows: WorldState["trace"] = []; // one Trace row per applied event, in seq order
  let running: WorldState = snapshots[0] as WorldState; // the fold so far, its trace left empty

  return {
    apply(event) {
      if (event.seq <= this.currentSeq()) return; // duplicate or out of order: ignored
      events.push(event);
      const next = applyEvent(running, event, layout); // its trace is just this event's row
      running = { ...next, trace: [] };
      rows.push(...next.trace);
      if (event.seq % SNAPSHOT_EVERY === 0) snapshots.push({ ...running, trace: [...rows] });
    },
    stateAt(seq) {
      // snapshots always has at least the seq-0 initial state (pushed at construction).
      let best = snapshots[0] as WorldState;
      for (const snap of snapshots) {
        if (snap.seq <= seq && snap.seq > best.seq) best = snap;
      }
      let state: WorldState = { ...best, trace: [] };
      const delta: WorldState["trace"] = [];
      for (const event of events) {
        if (event.seq <= best.seq) continue;
        if (event.seq > seq) break;
        state = applyEvent(state, event, layout);
        delta.push(...state.trace);
        state = { ...state, trace: [] };
      }
      return delta.length === 0 ? best : { ...state, trace: [...best.trace, ...delta] };
    },
    snapshotSeqs() {
      return snapshots.map((s) => s.seq).filter((seq) => seq > 0);
    },
    currentSeq() {
      return events.length > 0 ? (events[events.length - 1] as Event).seq : 0;
    },
  };
}
