// FR-WLD-11: one polite sentence for a screen reader when new recorded events reach the Story, not
// one announcement per row. Nothing is announced while the first rows load, on a replay (fixture or
// scrub: those are not new work) or when rows disappear. The text comes from the events' own
// summaries (HR-1).
import type { Event } from "@tilo/contracts";
import { useEffect, useRef, useState } from "react";

/** How long new rows may keep arriving before they are announced together. */
export const ANNOUNCE_DEBOUNCE_MS = 2000;

export const announcement = (added: number, latest: string): string =>
  `${added} new ${added === 1 ? "event" : "events"}. Latest: ${latest}`;

/** The sentence to announce, or "" for nothing. `enabled` is false while loading, on a replay, at a
 * replay point and once the run has ended. The first rows a client holds, and any change that is
 * not a tail append of the rows seen before (a different run, a reset), set a new baseline and say
 * nothing; only rows appended after that are news. */
export function useStoryAnnouncement(story: readonly Event[], enabled: boolean): string {
  const [text, setText] = useState("");
  const seen = useRef<{ count: number; seq: number } | null>(null);
  useEffect(() => {
    if (!enabled) {
      seen.current = null;
      setText("");
      return;
    }
    const mark = () => ({ count: story.length, seq: story[story.length - 1]?.seq ?? 0 });
    const base = seen.current;
    // The first rows a client holds are the log as it stood, not news: they set the baseline.
    if (base === null || base.count === 0 || story.length < base.count) {
      seen.current = mark();
      return;
    }
    if (story[base.count - 1]?.seq !== base.seq) {
      seen.current = mark(); // not a tail append of the rows seen: another run, or a reset
      return;
    }
    if (story.length === base.count) return;
    const timer = setTimeout(() => {
      const added = story.length - base.count;
      seen.current = mark();
      const last = story[story.length - 1];
      if (added > 0 && last) setText(announcement(added, last.summary));
    }, ANNOUNCE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [story, enabled]);
  return text;
}
