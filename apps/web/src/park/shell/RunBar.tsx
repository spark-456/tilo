// The run bar (RUN-INDICATOR; PRD 9.4 HR-1, HR-2): a small pill fixed at the bottom of the Park app that says
// Tilo is working. It draws only from the worlds the Api serves, the same recorded state the Worlds page shows:
//   - a world in state `running` (a recorded start, not yet completed, failed or paused): a ring and a label;
//   - a world in state `needs` (a recorded open card, the run is held): the static label, no ring;
//   - anything else, a failed read, or no worlds: nothing is drawn.
// The state is read on mount, when the page changes, when a decision or a started world changes, and, while a live
// run is showing, again every POLL_MS through the injected scheduler (so the end of a run takes the bar away; no
// clock here moves anything). A failed read hides the bar and stops the polling; the next page or decision change
// reads again. Live, only worlds the server listed count (a world the person started here that the list lacks is a
// canned stand-in, not a recorded run). On the fixture path only worlds the person started in this session count: the
// canned sample worlds are not runs that are happening (HR-2). Reduced motion and 'still' draw a still dot.
import { useEffect, useState, useSyncExternalStore } from "react";
import type { World } from "../api/types";
import { useParkApi, useParkStore, useSchedule } from "../app/context";
import { useParkRoute } from "../app/router";
import { useMotionOff } from "./motion";
import { runBarOf } from "./runStatus";

/** How often a live, running or held bar reads the worlds again. */
export const POLL_MS = 15 * 1000;

interface Read {
  worlds: World[];
  live: boolean;
}

export function RunBar() {
  const api = useParkApi();
  const store = useParkStore();
  const schedule = useSchedule();
  const route = useParkRoute();
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const off = useMotionOff();
  const [read, setRead] = useState<Read | null>(null);
  const [round, setRound] = useState(0);
  const page = route ? `${route.page}/${route.params.id ?? ""}` : "";

  // biome-ignore lint/correctness/useExhaustiveDependencies: `page` (a page change) and `round` (the poll) only re-run the read
  useEffect(() => {
    let current = true;
    const ids = new Set(state.added.map((w) => w.id));
    const sessionWorlds = new Set<World>(state.added);
    api
      .getWorlds(state.dec, state.added)
      .then((r) => {
        if (!current) return;
        const live = r.source === "live";
        // Live: only worlds the server's list served. The Api prepends the session's own started worlds (canned
        // sample objects: `running`, a template agent count) when the list lacks them; those are not recorded runs.
        // Fixture: only the worlds the person started here, minus the sample's agent count and activity line (the
        // fixture does not serve them as data), so the label is the plain "Working" and the world's name.
        const worlds = live
          ? r.data.filter((w) => !sessionWorlds.has(w))
          : r.data
              .filter((w) => ids.has(w.id))
              .map(({ activity: _activity, ...w }) => ({ ...w, agents: 0 }));
        setRead({ worlds, live });
      })
      .catch(() => current && setRead(null)); // an unreadable state is never shown as running
    return () => {
      current = false;
    };
  }, [api, state.dec, state.added, page, round]);

  const bar = read ? runBarOf(read.worlds) : null;
  const polling = bar !== null && read?.live === true;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `round` re-arms the next read after each one
  useEffect(() => {
    if (!polling) return;
    return schedule(() => setRound((n) => n + 1), POLL_MS);
  }, [polling, round, schedule]);

  if (!bar || !read) return null;
  const moving = bar.kind === "running" && !off;
  return (
    // <output> is the native status live region (implicit role "status", polite): the page's own toast and
    // loader card are the explicit role="status" elements, and this one must not be mistaken for them.
    <output
      className="park-shell__runbar"
      aria-live="polite"
      data-state={bar.kind}
      data-motion={off ? "off" : "on"}
      data-source={read.live ? "live" : "fixture"}
    >
      {moving ? (
        <span className="park-shell__ring" aria-hidden="true" />
      ) : (
        <span
          className={`park-shell__runbar-dot ${bar.kind === "held" ? "park-shell__runbar-dot--held" : ""}`}
          aria-hidden="true"
        />
      )}
      <span className="park-shell__runbar-label">{bar.label}</span>
      {bar.detail ? (
        <>
          <span className="park-shell__runbar-sep" aria-hidden="true">
            ·
          </span>
          <span className="park-shell__runbar-detail">{bar.detail}</span>
        </>
      ) : null}
    </output>
  );
}
