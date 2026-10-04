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

/** The sentence to announce, or "" for nothing. `enabled` is false while loading and on a replay. */
export function useStoryAnnouncement(story: readonly Event[], enabled: boolean): string {
  const [text, setText] = useState("");
  const seen = useRef<number | null>(null);
  useEffect(() => {
    if (!enabled) {
      seen.current = null;
      setText("");
      return;
    }
    if (seen.current === null || story.length < seen.current) {
      seen.current = story.length; // the rows already there are not news
      return;
    }
    if (story.length === seen.current) return;
    const timer = setTimeout(() => {
      const added = story.length - (seen.current ?? story.length);
      seen.current = story.length;
      const last = story[story.length - 1];
      if (added > 0 && last) setText(announcement(added, last.summary));
    }, ANNOUNCE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [story, enabled]);
  return text;
}
