// UI-STUDIO-2: Chat with your Tilo (design/studio-v2 "Tilo S Chat", canvas section 03). A direct question gets one
// helper over the real Quick answer path; the helper sits in a scene the person picks and its pose follows the
// request only (reading while the call is out, talking while a new answer is shown, done after). Nothing moves:
// every pose is still (HR-1, HR-2). No past chats are listed: the server keeps no Quick question or answer.
import { type FormEvent, useId, useState } from "react";
import type { AppCtx } from "../../app/AppCtx";
import { useParkStore } from "../../app/context";
import { usePageTitle } from "../../app/pageTitle";
import { SCENE_FLOOR, SCENE_SKY, SceneArt, SceneFront } from "../../chat/Scene";
import { SCENES, SCENE_LABEL, type SceneId, readScene, writeScene } from "../../chat/displayPrefs";
import { handDraft } from "../../chat/handoff";
import { type Turn, useQuickChat } from "../../chat/useQuickChat";
import { type SegmentOption, SegmentedControl } from "../../components";
import { Buddy, type BuddyMood } from "../../studio/Buddy";
import { SWITCH_WORDS, quickCostLine } from "../Home/homeData";
import "./Chat.css";

const SCENE_OPTIONS: SegmentOption[] = SCENES.map((s) => ({ value: s, label: SCENE_LABEL[s] }));

const BUBBLE_MAX = 220;
const clip = (text: string): string =>
  text.length > BUBBLE_MAX ? `${text.slice(0, BUBBLE_MAX).trimEnd()}…` : text;

/** What the helper says in the scene, from the last turn. */
function sceneLine(last: Turn | undefined, mood: BuddyMood): { label: string; text: string } {
  if (!last)
    return {
      label: "READY",
      text: "Ask me a quick question. I answer straight away and never act for you.",
    };
  if (last.state === "asking") return { label: "READING", text: "Reading your question…" };
  if (last.state === "answered")
    return { label: mood === "talking" ? "SPEAKING" : "ANSWERED", text: clip(last.text) };
  if (last.state === "switch")
    return { label: "THIS NEEDS A WORLD", text: SWITCH_WORDS[last.reason] };
  return { label: "NOT ANSWERED", text: last.message };
}

function statusLine(last: Turn | undefined, mood: BuddyMood): string {
  if (mood === "reading") return "Tilo is reading your question";
  if (mood === "talking") return "Tilo is answering · 1 helper";
  if (last?.state === "answered")
    return last.seconds > 0 ? `Answered in ${last.seconds}s` : "Answered";
  return "Ready when you are";
}

const totalCredits = (turns: readonly Turn[]): number | null => {
  let sum = 0;
  let any = false;
  for (const t of turns) {
    if (t.state === "answered" && !t.sample && t.cost?.credits !== undefined) {
      sum += t.cost.credits;
      any = true;
    }
  }
  return any ? sum : null;
};

function Face() {
  return (
    <span className="park-chat-face" aria-hidden="true">
      <span className="park-chat-face__visor">
        <span />
        <span />
      </span>
    </span>
  );
}

function Answer({
  turn,
  onWorld,
  onCopy,
}: {
  turn: Turn;
  onWorld: (question: string) => void;
  onCopy: ((text: string) => void) | null;
}) {
  if (turn.state === "asking")
    return (
      <div className="park-chat-turn">
        <Face />
        <div className="park-chat-turn__body">
          <div className="park-chat-meta">TILO · READING…</div>
        </div>
      </div>
    );
  if (turn.state === "answered") {
    const cost = turn.sample ? null : quickCostLine(turn.cost);
    const meta = [
      "TILO",
      turn.seconds > 0 ? `ANSWERED IN ${turn.seconds}S` : "ANSWERED",
      ...(cost ? [cost.toUpperCase()] : []),
    ].join(" · ");
    return (
      <div className="park-chat-turn">
        <Face />
        <div className="park-chat-turn__body">
          <div className="park-chat-meta">
            {meta}
            {turn.sample ? <span className="park-chat-sample">Sample answer</span> : null}
          </div>
          <p className="park-chat-text">{turn.text}</p>
          <div className="park-chat-actions">
            {onCopy ? (
              <button type="button" className="park-chat-quiet" onClick={() => onCopy(turn.text)}>
                Copy
              </button>
            ) : null}
            <button type="button" className="park-chat-soft" onClick={() => onWorld(turn.question)}>
              Make it a world →
            </button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="park-chat-turn">
      <Face />
      <div className="park-chat-turn__body">
        <div className="park-chat-meta">TILO</div>
        {turn.state === "switch" ? (
          <>
            <p className="park-chat-text">{`This needs a world. ${SWITCH_WORDS[turn.reason]}`}</p>
            <div className="park-chat-actions">
              <button
                type="button"
                className="park-chat-soft"
                onClick={() => onWorld(turn.question)}
              >
                Make it a world →
              </button>
            </div>
          </>
        ) : (
          <p className="park-chat-text park-chat-text--note">{turn.message}</p>
        )}
      </div>
    </div>
  );
}

export function ChatPage({ app }: { app: AppCtx }) {
  usePageTitle("Chat");
  const store = useParkStore();
  const chat = useQuickChat();
  const [scene, setScene] = useState<SceneId>(readScene);
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const last = chat.turns[chat.turns.length - 1];
  const line = sceneLine(last, chat.mood);
  const credits = totalCredits(chat.turns);
  const lastQuestion = last?.question ?? draft.trim();

  const send = (e: FormEvent) => {
    e.preventDefault();
    if (chat.ask(draft)) setDraft("");
  };
  const toWorld = (question: string) => {
    handDraft(question);
    app.go("home");
  };
  const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
  const copy = clipboard
    ? (text: string) => {
        clipboard.writeText(text).then(
          () => store.toast("Answer copied"),
          () => store.toast("Could not copy the answer"),
        );
      }
    : null;

  return (
    <div className="park-chat" data-testid="park-page-chat">
      <div className="park-chat-head">
        <h1 className="park-chat-h1">Chat with your Tilo</h1>
        <span className="park-chat-tag">QUICK ANSWER · 1 HELPER</span>
        <span className="park-chat-head__gap" />
        {credits !== null ? (
          <span className="park-chat-cost">{`This chat ${quickCostLine({ credits })?.replace("Cost ", "") ?? ""}`}</span>
        ) : null}
        <button
          type="button"
          className="park-chat-quiet park-chat-quiet--lg"
          disabled={lastQuestion === ""}
          onClick={() => toWorld(lastQuestion)}
        >
          Turn into a world
        </button>
      </div>
      <div className="park-chat-grid">
        <section
          aria-label="Your helper"
          className={`park-chat-scene park-chat-scene--${scene}`}
          style={{ background: SCENE_SKY[scene] }}
        >
          <SceneArt scene={scene} />
          <div className="park-chat-scene__buddy" style={{ bottom: SCENE_FLOOR[scene] }}>
            <Buddy mood={chat.mood} size={260} />
          </div>
          <SceneFront scene={scene} />
          <div className="park-chat-scene__top">
            <SegmentedControl
              label="Scene"
              options={SCENE_OPTIONS}
              value={scene}
              onChange={(v) => {
                const next = SCENES.find((s) => s === v) ?? "office";
                setScene(next);
                writeScene(next);
              }}
            />
          </div>
          <div className="park-chat-speech" data-mood={chat.mood}>
            <div className="park-chat-speech__label">{line.label}</div>
            {line.text}
          </div>
          {/* biome-ignore lint/a11y/useSemanticElements: the helper's state line is a status, not a form output */}
          <div role="status" className="park-chat-status" data-mood={chat.mood}>
            <span className="park-chat-status__dot" aria-hidden="true" />
            <span>{statusLine(last, chat.mood)}</span>
          </div>
        </section>
        <section aria-label="Conversation" className="park-chat-thread">
          <div className="park-chat-log" role="log" aria-label="Messages">
            {chat.turns.length === 0 ? (
              <div className="park-chat-intro">
                <p className="park-chat-intro__title">Ask a direct question</p>
                <p className="park-chat-intro__line">
                  One helper answers right away. Past chats are not kept, so this page starts empty
                  each visit.
                </p>
              </div>
            ) : (
              chat.turns.map((t) => (
                <div key={t.id} className="park-chat-pair">
                  <div className="park-chat-you">{t.question}</div>
                  <Answer turn={t} onWorld={toWorld} onCopy={copy} />
                </div>
              ))
            )}
          </div>
          <form className="park-chat-compose" onSubmit={send}>
            <div className="park-chat-box">
              <label htmlFor={inputId} className="park-chat-sr">
                Ask a question
              </label>
              <input
                id={inputId}
                className="park-chat-input"
                type="text"
                autoComplete="off"
                value={draft}
                placeholder={chat.turns.length ? "Ask a follow-up…" : "Ask a question…"}
                onChange={(e) => setDraft(e.target.value)}
              />
              <span className="park-chat-mode">
                <span className="park-chat-mode__dot" aria-hidden="true" />
                Quick answer
              </span>
              <button
                type="submit"
                className="park-chat-send"
                aria-label="Send"
                aria-disabled={chat.busy || undefined}
              >
                ↑
              </button>
            </div>
            {chat.note ? (
              <p role="alert" className="park-chat-note">
                {chat.note}
              </p>
            ) : null}
            <p className="park-chat-foot">
              Quick answers use one helper and never act for you. Need sending, buying or booking?
              Make it a world.
            </p>
          </form>
        </section>
      </div>
    </div>
  );
}
