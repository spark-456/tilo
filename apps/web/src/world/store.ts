// FR-WLD-04 / PRD 9.6: "Replay: scrub any finished run; the reducer is deterministic and
// snapshots every 250 events." Snapshots are immutable — later apply() calls build a new state
// object (reducer.ts already never mutates in place) and never touch an already-taken snapshot.
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

  return {
    apply(event) {
      if (event.seq <= this.currentSeq()) return; // duplicate or out of order: ignored
      events.push(event);
      if (event.seq % SNAPSHOT_EVERY === 0) {
        snapshots.push(this.stateAt(event.seq));
      }
    },
    stateAt(seq) {
      // snapshots always has at least the seq-0 initial state (pushed at construction).
      let best = snapshots[0] as WorldState;
      for (const snap of snapshots) {
        if (snap.seq <= seq && snap.seq > best.seq) best = snap;
      }
      let state = best;
      for (const event of events) {
        if (event.seq <= best.seq) continue;
        if (event.seq > seq) break;
        state = applyEvent(state, event, layout);
      }
      return state;
    },
    snapshotSeqs() {
      return snapshots.map((s) => s.seq).filter((seq) => seq > 0);
    },
    currentSeq() {
      return events.length > 0 ? (events[events.length - 1] as Event).seq : 0;
    },
  };
}
