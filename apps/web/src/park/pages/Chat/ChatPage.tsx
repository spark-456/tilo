// UI-STUDIO-2: Chat with your Tilo (design/studio-v2 "Tilo S Chat", canvas section 03). A direct question gets one
// helper over the real Quick answer path; the helper sits in a scene the person picks and its pose follows the
// request only (reading while the call is out, talking while a new answer is shown, done after). Nothing moves:
// every pose is still (HR-1, HR-2). No past chats are listed: the server keeps no Quick question or answer.
import { type FormEvent, useId, useState } from "react";
import { Icon, Buddy as TiloBuddy } from "../../../design/tilo-t";
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

function statusLine(last: Turn | undefined, mood: BuddyMood): string {
  if (mood === "reading") return "Tilo is reading your question";
  if (mood === "talking") return "Tilo is answering";
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

function Face({ mood }: { mood: BuddyMood }) {
  const pose = mood === "reading" ? "think" : mood === "talking" ? "talk" : "idle";
  return (
    <span className="park-chat-face" aria-hidden="true">
      <TiloBuddy mood={pose} size={44} />
    </span>
  );
}

function Answer({
  turn,
  onWorld,
  onCopy,
  mood,
}: {
  turn: Turn;
  onWorld: (question: string) => void;
  onCopy: ((text: string) => void) | null;
  mood: BuddyMood;
}) {
  if (turn.state === "asking")
    return (
      <div className="park-chat-turn">
        <Face mood={mood} />
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
        <Face mood={mood} />
        <div className="park-chat-turn__body">
          <div className="park-chat-meta">
            {meta}
            {turn.sample ? <span className="park-chat-sample">Sample answer</span> : null}
          </div>
          <div className="park-chat-result-card">
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
      </div>
    );
  }
  return (
    <div className="park-chat-turn">
      <Face mood={mood} />
      <div className="park-chat-turn__body">
        <div className="park-chat-meta">TILO</div>
        {turn.state === "switch" ? (
          <div className="park-chat-world-card">
            <strong>This needs a world.</strong>
            <p>{SWITCH_WORDS[turn.reason]}</p>
            <div className="park-chat-actions">
              <button
                type="button"
                className="park-chat-soft"
                onClick={() => onWorld(turn.question)}
              >
                Make it a world →
              </button>
            </div>
          </div>
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
      <div className="park-chat-grid">
        <aside className="park-chat-rail">
          <nav aria-label="Chat history" className="park-chat-history">
            <button
              type="button"
              className="park-chat-new"
              disabled={chat.busy}
              onClick={() => {
                chat.clear();
                setDraft("");
              }}
            >
              <Icon name="plus" size={18} /> New chat
            </button>
            <span className="park-chat-history__label">Current chat</span>
            {chat.turns.map((turn) => (
              <a key={turn.id} href={`#chat-turn-${turn.id}`} className="park-chat-history__turn">
                {turn.question}
              </a>
            ))}
            {chat.turns.length === 0 ? (
              <p className="park-chat-history__empty">No questions in this chat yet.</p>
            ) : null}
          </nav>
          <section
            aria-label="Your helper"
            className={`park-chat-scene park-chat-scene--${scene}`}
            style={{ background: SCENE_SKY[scene] }}
          >
            <SceneArt scene={scene} />
            <div className="park-chat-scene__buddy" style={{ bottom: SCENE_FLOOR[scene] }}>
              <Buddy mood={chat.mood} size={140} />
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
            {/* biome-ignore lint/a11y/useSemanticElements: the helper's state line is a status, not a form output */}
            <div role="status" className="park-chat-status" data-mood={chat.mood}>
              <span className="park-chat-status__dot" aria-hidden="true" />
              <span>{statusLine(last, chat.mood)}</span>
            </div>
          </section>
        </aside>
        <div className="park-chat-main">
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
          <section aria-label="Conversation" className="park-chat-thread">
            <div className="park-chat-log" role="log" aria-label="Messages">
              {chat.turns.length === 0 ? (
                <div className="park-chat-intro">
                  <p className="park-chat-intro__title">Ask a direct question</p>
                  <p className="park-chat-intro__line">
                    One helper answers right away. Past chats are not kept, so this page starts
                    empty each visit.
                  </p>
                </div>
              ) : (
                chat.turns.map((t) => (
                  <div key={t.id} id={`chat-turn-${t.id}`} className="park-chat-pair">
                    <div className="park-chat-you">{t.question}</div>
                    <Answer
                      turn={t}
                      onWorld={toWorld}
                      onCopy={copy}
                      mood={t.id === last?.id ? chat.mood : "idle"}
                    />
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
                  <Icon name="send" size={20} />
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
    </div>
  );
}
