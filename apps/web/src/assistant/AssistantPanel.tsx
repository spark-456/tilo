// S-30 assistant panel shell (FR-PA-12, FR-PA-18). A launcher on every screen opens an overlay: a
// side panel on desktop, a bottom sheet on a phone. It is fixed over the page, so opening it moves
// nothing (CLS 0). It shows the screen's context as a chip, traps focus while open, closes on Esc and
// hands focus back to the launcher, and keeps its open state for the browser session. Answers come
// from an adapter (fixture for now). It never animates: no transition, no streaming effect.
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { usePathname } from "../router";
import { useScrolls } from "../screens/kit";
import { useSelection } from "../world/selection";
import { type AssistantAdapter, type AssistantReply, fixtureAdapter } from "./adapter";
import { contextOf, worldOf } from "./context";

const OPEN_KEY = "tilo.assistant.open";
const readOpen = (): boolean => {
  try {
    return window.sessionStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false; // storage can be blocked; the panel then simply starts closed
  }
};
const writeOpen = (open: boolean) => {
  try {
    if (open) window.sessionStorage.setItem(OPEN_KEY, "1");
    else window.sessionStorage.removeItem(OPEN_KEY);
  } catch {
    // not persisted
  }
};

interface Turn {
  readonly id: number;
  readonly from: "you" | "tilo";
  readonly text: string;
  readonly sources: AssistantReply["sources"];
}

const FOCUSABLE =
  "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href]";

export function AssistantPanel({ adapter = fixtureAdapter }: { adapter?: AssistantAdapter }) {
  const [open, setOpen] = useState(readOpen);
  const [turns, setTurns] = useState<readonly Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const path = usePathname();
  const world = worldOf(path);
  const [selected] = useSelection(world ?? "");
  const context = contextOf(path, world ? selected : null);
  const panel = useRef<HTMLDialogElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const scrolls = useScrolls(log); // a log that scrolls is a keyboard stop (WCAG 2.1.1)
  const wasOpen = useRef(false);
  const next = useRef(1);

  useEffect(() => {
    writeOpen(open);
    if (open) input.current?.focus();
    else if (wasOpen.current) launcher.current?.focus(); // hand focus back, once, after a close
    wasOpen.current = open;
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      return;
    }
    if (e.key !== "Tab") return;
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const [first, last] = [items[0], items[items.length - 1]];
    if (!first || !last) return;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { id: next.current++, from: "you", text, sources: [] }]);
    try {
      const reply = await adapter.ask(text, context);
      setTurns((t) => [...t, { id: next.current++, from: "tilo", ...reply }]);
    } catch {
      setTurns((t) => [
        ...t,
        {
          id: next.current++,
          from: "tilo",
          text: "That did not work. Try asking again.",
          sources: [],
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        ref={launcher}
        type="button"
        className="assistant-open"
        data-testid="assistant-open"
        data-assistant-control
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        Ask Tilo
      </button>
      {open && (
        <dialog
          ref={panel}
          className="assistant-panel"
          data-testid="assistant-panel"
          open
          aria-modal="true"
          aria-label="Assistant"
          onKeyDown={onKeyDown}
        >
          <div className="assistant-head">
            <h2>Assistant</h2>
            <button type="button" className="assistant-close" onClick={() => setOpen(false)}>
              Close
            </button>
          </div>
          <p className="assistant-context" data-testid="assistant-context">
            You are on: {context.label}
            {context.record ? ` · ${context.record}` : ""}
          </p>
          <div
            ref={log}
            className="assistant-log"
            role="log"
            aria-live="polite"
            aria-label="Conversation"
            tabIndex={scrolls ? 0 : undefined}
          >
            {turns.length === 0 ? (
              <p className="assistant-empty">
                Ask what is on your plate, what is waiting for you, or what changed. This is a
                preview: answers are not connected yet.
              </p>
            ) : (
              <ul>
                {turns.map((t) => (
                  <li key={t.id} data-from={t.from}>
                    <b>{t.from === "you" ? "You" : "Tilo"}</b>
                    <p>{t.text}</p>
                    {t.sources.length > 0 && (
                      <ul className="assistant-sources">
                        {t.sources.map((s) => (
                          <li key={s.href}>
                            <a href={s.href}>{s.label}</a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <form className="assistant-form" onSubmit={ask}>
            <label className="assistant-label" htmlFor="assistant-question">
              Ask Tilo
            </label>
            <input
              ref={input}
              id="assistant-question"
              type="text"
              autoComplete="off"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button type="submit" className="secondary" disabled={busy}>
              Send
            </button>
          </form>
        </dialog>
      )}
    </>
  );
}
