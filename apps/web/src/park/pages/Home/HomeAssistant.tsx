import { useState, type FormEvent } from "react";
import { Buddy as TiloTBuddy, type TiloMood } from "../../../design/tilo-t/Buddy";
import { useQuickChat } from "../../chat/useQuickChat";
import "./Home.css";

export interface HomeContextChip {
  readonly id: string;
  readonly label: string;
  readonly prompt: string;
  readonly detail: string;
}

const replyText = (turn: ReturnType<typeof useQuickChat>["turns"][number]): string =>
  turn.state === "asking"
    ? "Reading your question…"
    : turn.state === "answered"
      ? turn.text
      : turn.state === "switch"
        ? "This needs a world. Try Make a world from the main prompt box."
        : turn.message;

export function HomeAssistant({ contexts }: { contexts: readonly HomeContextChip[] }) {
  const chat = useQuickChat();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  // triggeredBy: assistant.asked / assistant.replied; the Buddy follows the real Quick request and reply state.
  const mood: TiloMood =
    chat.mood === "reading"
      ? "think"
      : chat.mood === "talking"
        ? "talk"
        : chat.mood === "done"
          ? "happy"
          : "idle";
  const ask = (e: FormEvent) => {
    e.preventDefault();
    const query = draft.trim();
    if (!query) return;
    const details = contexts
      .filter((c) => selected.includes(c.id))
      .map((c) => `${c.label}: ${c.detail}`);
    const withContext = details.length ? `${query}\n\n${details.join("\n")}` : query;
    if (chat.ask(withContext)) setDraft("");
  };

  return (
    <div className="park-home-assistant-wrap">
      <button
        type="button"
        className="park-home-assistant-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <TiloTBuddy mood="idle" size={60} /> Ask Tilo
      </button>
      {open ? (
        <section className="park-home-assistant" aria-label="Ask Tilo">
          <header className="park-home-assistant__head">
            <TiloTBuddy mood={mood} size={60} />
            <div>
              <strong>Ask Tilo</strong>
              <span>Answers use the context you choose.</span>
            </div>
            <button type="button" aria-label="Close Ask Tilo" onClick={() => setOpen(false)}>×</button>
          </header>
          {contexts.length > 0 ? (
            <div className="park-home-assistant__contexts" aria-label="Context">
              <span>USING</span>
              {contexts.map((context) => {
                const active = selected.includes(context.id);
                return (
                  <button
                    key={context.id}
                    type="button"
                    aria-pressed={active}
                    className={active ? "is-selected" : ""}
                    onClick={() => {
                      setSelected((current) =>
                        active
                          ? current.filter((id) => id !== context.id)
                          : [...current, context.id],
                      );
                      setDraft(context.prompt);
                    }}
                  >
                    {context.label}
                  </button>
                );
              })}
            </div>
          ) : null}
          <div className="park-home-assistant__messages" role="log" aria-label="Assistant messages">
            {chat.turns.slice(-2).map((turn) => (
              <div className="park-home-assistant__turn" key={turn.id}>
                <span className="park-home-assistant__question">{turn.question.split("\n\n")[0]}</span>
                <span className="park-home-assistant__answer">
                  {turn.state === "answered" && turn.sample ? (
                    <b>Sample answer · </b>
                  ) : null}
                  {replyText(turn)}
                </span>
              </div>
            ))}
            {chat.turns.length === 0 ? <p>Choose context or ask a quick question.</p> : null}
          </div>
          {chat.note ? (
            <p className="park-home-assistant__note" role="alert">
              {chat.note}
            </p>
          ) : null}
          <form className="park-home-assistant__form" onSubmit={ask}>
            <label className="park-home-sr" htmlFor="park-home-assistant-input">
              Ask Tilo a question
            </label>
            <input
              id="park-home-assistant-input"
              aria-label="Ask Tilo a question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about your work…"
            />
            <button type="submit" aria-label="Send" disabled={chat.busy}>↑</button>
          </form>
        </section>
      ) : null}
    </div>
  );
}
