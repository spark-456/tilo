// UI-STUDIO-2: one conversation with the single helper, over the real Quick answer path (COST-FAST-1: `POST /intake`
// with mode=quick through `askQuick`). Shared by the Chat page and the Tilo bubble. A turn is what the server
// answered, or why it did not; nothing is invented. The helper's mood is derived from the request alone:
// reading while the call is out, talking while the answer that just arrived is shown, done once it has been shown.
// The conversation lives in this component only: the server keeps no Quick question or answer (quick.py), so there
// is no history to list (docs/open-questions.md BQ-STUDIO-2).
import { useCallback, useEffect, useRef, useState } from "react";
import { sessionView } from "../../api/ClientProvider";
import type { QuickIntakeResult } from "../../api/http";
import type { SkillMatch, SkillRef } from "../../api/skillRoute";
import { askQuick } from "../api/index";
import type { QuickCost, SwitchReason } from "../api/types";
import { useParkApi, useSchedule } from "../app/context";
import { quickErrorMessage } from "../app/store";
import { QUICK_MAX_CHARS } from "../pages/Home/homeData";
import type { BuddyMood } from "../studio/Buddy";
import {
  type SavedChat,
  loadServerChats,
  readChats,
  saveChats,
  saveServerChat,
} from "./chatHistory";

export type Turn =
  | { id: number; question: string; state: "asking" }
  | {
      id: number;
      question: string;
      state: "answered";
      text: string;
      cost: QuickCost | null;
      memorySuggestion?: Extract<QuickIntakeResult, { kind: "answered" }>["memorySuggestion"];
      /** The fixture Api answered: a labelled sample, never shown as a live answer. */
      sample: boolean;
      /** Seconds from send to answer, measured here. */
      seconds: number;
      skill?: SkillMatch;
    }
  | { id: number; question: string; state: "switch"; reason: SwitchReason; skill?: SkillMatch }
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
  ask(text: string, ref?: SkillRef | null): boolean;
  /** Starts a fresh local session when no request is in flight. */
  clear(): void;
  readonly history: readonly SavedChat[];
  select(id: string): void;
}

export function useQuickChat(
  now: () => number = Date.now,
  pageContext?: string,
  persist = false,
): QuickChat {
  const api = useParkApi();
  const schedule = useSchedule();
  const owner = persist ? (sessionView.identity()?.email ?? null) : null;
  const [history, setHistory] = useState<SavedChat[]>(() => readChats(owner));
  const [activeId, setActiveId] = useState(() => readChats(owner)[0]?.id ?? crypto.randomUUID());
  const [turns, setTurns] = useState<Turn[]>(() => [...(readChats(owner)[0]?.turns ?? [])]);
  const [talkingId, setTalkingId] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const busyRef = useRef(false);
  const nextId = useRef(Math.max(0, ...turns.map((turn) => turn.id)) + 1);
  const alive = useRef(true);
  const cancelTalk = useRef<(() => void) | null>(null);
  const saving = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      cancelTalk.current?.();
    };
  }, []);
  useEffect(() => {
    if (!persist || !owner) return;
    let live = true;
    loadServerChats()
      .then((remote) => {
        const latest = remote[0];
        if (!live || !latest) return;
        setHistory((current) => {
          const merged = new Map(current.map((entry) => [entry.id, entry]));
          for (const entry of remote) {
            const local = merged.get(entry.id);
            if (!local || local.updatedAt < entry.updatedAt) merged.set(entry.id, entry);
          }
          const next = [...merged.values()].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 100);
          saveChats(owner, next);
          return next;
        });
        setTurns((current) => {
          if (current.length) return current;
          setActiveId(latest.id);
          nextId.current = Math.max(0, ...latest.turns.map((turn) => turn.id)) + 1;
          return [...latest.turns];
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [owner, persist]);
  useEffect(() => {
    const first = turns[0];
    if (!persist || !owner || !first || turns.some((turn) => turn.state === "asking")) return;
    setHistory((current) => {
      const chat: SavedChat = {
        id: activeId,
        title: first.question.slice(0, 60),
        updatedAt: now(),
        turns,
      };
      const next = [chat, ...current.filter((entry) => entry.id !== activeId)]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, 100);
      saveChats(owner, next);
      saving.current = saving.current.catch(() => undefined).then(() => saveServerChat(chat));
      return next;
    });
  }, [activeId, now, owner, persist, turns]);

  const ask = useCallback(
    (raw: string, ref: SkillRef | null = null): boolean => {
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
        resolve(
          askQuick(
            api,
            "quick",
            pageContext ? `${question}\nYou're on ${pageContext}.` : question,
            ref ? [ref] : [],
          ),
        ),
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
                  ...(data.memorySuggestion ? { memorySuggestion: data.memorySuggestion } : {}),
                  sample: source !== "live",
                  seconds: Math.max(0, Math.round((now() - started) / 1000)),
                  ...(data.skill ? { skill: data.skill } : {}),
                }
              : {
                  id,
                  question,
                  state: "switch",
                  reason: data.reason,
                  ...(data.skill ? { skill: data.skill } : {}),
                },
          ),
        (e: unknown) => settle({ id, question, state: "error", message: quickErrorMessage(e) }),
      );
      return true;
    },
    [api, schedule, now, pageContext],
  );

  const last = turns[turns.length - 1];
  return {
    turns,
    busy: last?.state === "asking",
    mood: moodOf(last, talkingId),
    note,
    ask,
    clear: () => {
      if (busyRef.current) return;
      cancelTalk.current?.();
      cancelTalk.current = null;
      setTalkingId(null);
      setNote(null);
      setTurns([]);
      setActiveId(crypto.randomUUID());
    },
    history,
    select: (id: string) => {
      if (busyRef.current) return;
      const chosen = history.find((entry) => entry.id === id);
      if (!chosen) return;
      cancelTalk.current?.();
      setTalkingId(null);
      setNote(null);
      setActiveId(id);
      setTurns([...chosen.turns]);
      nextId.current = Math.max(0, ...chosen.turns.map((turn) => turn.id)) + 1;
    },
  };
}
