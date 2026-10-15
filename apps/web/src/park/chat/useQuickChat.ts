// UI-STUDIO-2: one conversation with the single helper, over the real Quick answer path (COST-FAST-1: `POST /intake`
// with mode=quick through `askQuick`). Shared by the Chat page and the Tilo bubble. A turn is what the server
// answered, or why it did not; nothing is invented. The helper's mood is derived from the request alone:
// reading while the call is out, talking while the answer that just arrived is shown, done once it has been shown.
// The conversation lives in this component only: the server keeps no Quick question or answer (quick.py), so there
// is no history to list (docs/open-questions.md BQ-STUDIO-2).
import { useCallback, useEffect, useRef, useState } from "react";
import { type QuickClientContext, askQuick } from "../api/index";
import type { QuickCost, SwitchReason } from "../api/types";
import { useParkApi, useSchedule } from "../app/context";
import { quickErrorMessage } from "../app/store";
import { QUICK_MAX_CHARS } from "../pages/Home/homeData";
import type { BuddyMood } from "../studio/Buddy";

export type Turn =
  | { id: number; question: string; state: "asking" }
  | {
      id: number;
      question: string;
      state: "answered";
      text: string;
      cost: QuickCost | null;
      /** The fixture Api answered: a labelled sample, never shown as a live answer. */
      sample: boolean;
      /** Seconds from send to answer, measured here. */
      seconds: number;
    }
  | { id: number; question: string; state: "switch"; reason: SwitchReason }
  | { id: number; question: string; state: "error"; message: string };

/** How long the helper is shown talking after an answer lands: about a reading pace, 1.5 s to 6 s. */
export function talkMs(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.min(6000, Math.max(1500, words * 250));
}

/** The helper's mood from the request state only (no idle loop, no motion: the pose is still). */
export function moodOf(last: Turn | undefined, talkingId: number | null): BuddyMood {
  if (!last) return "idle";
  if (last.state === "asking") return "reading";
  if (last.state === "answered") return talkingId === last.id ? "talking" : "done";
  return "idle";
}

/** A question that is not sent, in plain words; null when it may go. */
export function refusal(text: string): string | null {
  if (text === "") return "Type your question first.";
  const length = Array.from(text).length;
  if (length > QUICK_MAX_CHARS)
    return `A quick question can be up to ${QUICK_MAX_CHARS} characters; this one is ${length}. Shorten it, or make it a world.`;
  return null;
}

export interface QuickChat {
  readonly turns: readonly Turn[];
  readonly busy: boolean;
  readonly mood: BuddyMood;
  /** A line that was not sent (empty or too long); cleared by the next ask. */
  readonly note: string | null;
  /** Sends `text`; returns false when it was not sent (busy, empty or too long). */
  ask(text: string): boolean;
}

export function useQuickChat(now: () => number = Date.now): QuickChat {
  const api = useParkApi();
  const schedule = useSchedule();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [talkingId, setTalkingId] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const busyRef = useRef(false);
  const nextId = useRef(1);
  const alive = useRef(true);
  const cancelTalk = useRef<(() => void) | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      cancelTalk.current?.();
    };
  }, []);

  const ask = useCallback(
    (raw: string): boolean => {
      if (busyRef.current) return false;
      const question = raw.trim();
      const refused = refusal(question);
      setNote(refused);
      if (refused !== null) return false;
      busyRef.current = true;
      cancelTalk.current?.();
      cancelTalk.current = null;
      setTalkingId(null);
      const id = nextId.current++;
      const started = now();
      const context: QuickClientContext = {
        route: typeof window === "undefined" ? "/chat" : window.location.pathname,
        history: turns
          .filter((turn): turn is Extract<Turn, { state: "answered" }> => turn.state === "answered")
          .slice(-6)
          .map((turn) => ({
            question: turn.question.slice(0, 500),
            answer: turn.text.slice(0, 500),
          })),
      };
      setTurns((t) => [...t, { id, question, state: "asking" }]);
      const settle = (turn: Turn) => {
        busyRef.current = false;
        if (!alive.current) return;
        setTurns((t) => t.map((x) => (x.id === id ? turn : x)));
        if (turn.state === "answered") {
          setTalkingId(id);
          cancelTalk.current = schedule(() => {
            cancelTalk.current = null;
            setTalkingId((current) => (current === id ? null : current));
          }, talkMs(turn.text));
        }
      };
      new Promise<Awaited<ReturnType<typeof askQuick>>>((resolve) =>
        resolve(askQuick(api, "quick", question, context)),
      ).then(
        ({ data, source }) =>
          settle(
            data.kind === "answered"
              ? {
                  id,
                  question,
                  state: "answered",
                  text: data.text,
                  cost: data.cost,
                  sample: source !== "live",
                  seconds: Math.max(0, Math.round((now() - started) / 1000)),
                }
              : { id, question, state: "switch", reason: data.reason },
          ),
        (e: unknown) => settle({ id, question, state: "error", message: quickErrorMessage(e) }),
      );
      return true;
    },
    [api, schedule, now, turns],
  );

  const last = turns[turns.length - 1];
  return {
    turns,
    busy: last?.state === "asking",
    mood: moodOf(last, talkingId),
    note,
    ask,
  };
}
