// UI-STUDIO-2: the Tilo bubble (design/studio-v2 "Tilo S Bubble"): a round button bottom right that the person can
// drag anywhere, and a compact chat that asks over the same real Quick answer path as the Chat page. Its place is
// display state (browser storage, try/catch); arrow keys move it too, and "Back to the corner" puts it back, so
// dragging is never the only way (WCAG 2.2 2.5.7). Nothing moves by itself: no pulse, no blink, no "online" dot.
import {
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { PAGE_LABEL, type PageId } from "../app/AppCtx";
import { type BubblePos, readBubblePos, writeBubblePos } from "../chat/displayPrefs";
import { type Turn, useQuickChat } from "../chat/useQuickChat";
import { SWITCH_WORDS } from "../pages/Home/homeData";
import { Buddy } from "../studio/Buddy";
import "./TiloBubble.css";

const SIZE = 64;
const EDGE = 8;
const STEP = 16;
const DRAG_FROM = 4;

/** The default place: 40px from the corner on a desktop, clear of the run bar on a phone. */
export const homePos = (vw: number): BubblePos =>
  vw > 0 && vw < 840 ? { right: 16, bottom: 72 } : { right: 40, bottom: 40 };

/** Keeps the whole bubble on screen. */
export function clampPos(p: BubblePos, vw: number, vh: number): BubblePos {
  const maxR = Math.max(EDGE, vw - SIZE - EDGE);
  const maxB = Math.max(EDGE, vh - SIZE - EDGE);
  const c = (n: number, max: number) => Math.round(Math.min(Math.max(n, EDGE), max));
  return { right: c(p.right, maxR), bottom: c(p.bottom, maxB) };
}

function Said({ turn }: { turn: Turn }) {
  const reply =
    turn.state === "asking"
      ? "Reading your question…"
      : turn.state === "answered"
        ? turn.text
        : turn.state === "switch"
          ? `This needs a world. ${SWITCH_WORDS[turn.reason]}`
          : turn.message;
  return (
    <>
      <div className="park-bubble__you">{turn.question}</div>
      <div className="park-bubble__tilo">
        {turn.state === "answered" && turn.sample ? (
          <span className="park-bubble__sample">Sample answer</span>
        ) : null}
        {reply}
      </div>
    </>
  );
}

export function TiloBubble({
  page,
  vw,
  vh,
  go,
}: {
  page: PageId | null;
  vw: number;
  vh: number;
  go: (page: PageId) => void;
}) {
  const chat = useQuickChat();
  const [saved, setSaved] = useState<BubblePos | null>(readBubblePos);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const drag = useRef<{ x: number; y: number; from: BubblePos; moved: boolean } | null>(null);
  const dragged = useRef(false);
  const button = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const panelId = useId();
  const inputId = useId();
  const pos = clampPos(saved ?? homePos(vw), vw || 1440, vh || 900);

  const place = (next: BubblePos | null, keep: boolean) => {
    const p = next === null ? null : clampPos(next, vw || 1440, vh || 900);
    setSaved(p);
    if (keep) writeBubblePos(p);
  };
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  const closeNow = useRef(close);
  closeNow.current = close;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) closeNow.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const down = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    dragged.current = false;
    drag.current = { x: e.clientX, y: e.clientY, from: pos, moved: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const move = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_FROM) return;
    d.moved = true;
    place({ right: d.from.right - dx, bottom: d.from.bottom - dy }, false);
  };
  const up = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!d?.moved) return;
    dragged.current = true; // the click that follows a drag is not an open
    place(
      { right: d.from.right - (e.clientX - d.x), bottom: d.from.bottom - (e.clientY - d.y) },
      true,
    );
  };
  const nudge = (e: KeyboardEvent<HTMLButtonElement>) => {
    const by: Record<string, [number, number]> = {
      ArrowLeft: [STEP, 0],
      ArrowRight: [-STEP, 0],
      ArrowUp: [0, STEP],
      ArrowDown: [0, -STEP],
    };
    const d = by[e.key];
    if (!d) return;
    e.preventDefault();
    place({ right: pos.right + d[0], bottom: pos.bottom + d[1] }, true);
  };
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (chat.ask(draft)) setDraft("");
  };
  const goTo = (p: PageId) => {
    setOpen(false);
    go(p);
  };

  // The panel opens above the bubble, or below it when the bubble sits in the top half.
  const width = Math.min(384, (vw || 1440) - 2 * EDGE);
  const right = Math.min(Math.max(pos.right, EDGE), Math.max(EDGE, (vw || 1440) - width - EDGE));
  const above = pos.bottom < (vh || 900) / 2;
  const recent = chat.turns.slice(-2);

  return (
    <>
      {open ? (
        <dialog
          open
          id={panelId}
          aria-label="Your Tilo"
          className="park-bubble__panel"
          style={{
            right,
            width,
            ...(above
              ? { bottom: pos.bottom + SIZE + 16 }
              : { top: (vh || 900) - pos.bottom + 16 }),
          }}
        >
          <div className="park-bubble__head">
            <div className="park-bubble__face">
              <Buddy mood={chat.mood} size={50} />
            </div>
            <div className="park-bubble__who">
              <span className="park-bubble__name">Your Tilo</span>
              <span className="park-bubble__sub">Quick answers from one helper</span>
            </div>
            <button
              type="button"
              className="park-bubble__icon"
              aria-label="Open the full chat"
              title="Open the full chat"
              onClick={() => goTo("chat")}
            >
              ↗
            </button>
            <button
              type="button"
              className="park-bubble__icon"
              aria-label="Close"
              title="Close"
              onClick={close}
            >
              ×
            </button>
          </div>
          <div className="park-bubble__body">
            {page ? (
              <span className="park-bubble__where">{`You’re on ${PAGE_LABEL[page]}`}</span>
            ) : null}
            {recent.length > 0 ? (
              <div className="park-bubble__log" role="log" aria-label="Messages">
                {recent.map((t) => (
                  <Said key={t.id} turn={t} />
                ))}
              </div>
            ) : (
              <div className="park-bubble__go">
                <button type="button" onClick={() => goTo("home")}>
                  Start a task
                </button>
                <button type="button" onClick={() => goTo("worlds")}>
                  Your worlds
                </button>
                <button type="button" onClick={() => goTo("agenda")}>
                  Agenda
                </button>
                <button type="button" onClick={() => place(null, true)}>
                  Back to the corner
                </button>
              </div>
            )}
            {chat.note ? (
              <p role="alert" className="park-bubble__note">
                {chat.note}
              </p>
            ) : null}
          </div>
          <form className="park-bubble__form" onSubmit={send}>
            <label htmlFor={inputId} className="park-bubble__sr">
              Ask a quick question
            </label>
            <input
              ref={input}
              id={inputId}
              type="text"
              autoComplete="off"
              className="park-bubble__input"
              placeholder="Ask a quick question…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              type="submit"
              className="park-bubble__send"
              aria-label="Send"
              aria-disabled={chat.busy || undefined}
            >
              ↑
            </button>
          </form>
        </dialog>
      ) : null}
      <button
        ref={button}
        type="button"
        className="park-bubble"
        aria-label="Your Tilo: quick answers. Drag, or use the arrow keys, to move it"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        style={{ right: pos.right, bottom: pos.bottom }}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onKeyDown={nudge}
        onClick={() => {
          if (dragged.current) {
            dragged.current = false;
            return;
          }
          if (open) close();
          else setOpen(true);
        }}
      >
        <span className="park-bubble__visor" aria-hidden="true">
          <span />
          <span />
          <span className="park-bubble__smile" />
        </span>
      </button>
    </>
  );
}
