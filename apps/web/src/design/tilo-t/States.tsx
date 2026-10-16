// The shared Tilo T states (design/tilo-t "Tilo T State"): empty, loading (skeleton) and error. Reuse these; do not invent new ones.
// Trigger: the loading state shows while a request is pending and its shimmer is loading chrome (ambient); the caption names
// what is loading, never a made-up step. The error state is shown when a request failed, and says what happened.
import type { CSSProperties, ReactNode } from "react";
import { Buddy, type TiloMood } from "./Buddy";
import { Icon } from "./Icon";
import "./states.css";

export type LoadingLayout = "grid" | "list" | "split" | "calendar" | "world" | "chat";

/** A state action: one primary per screen (UX-1), the rest quiet. */
export function StateAction({
  children,
  onClick,
  quiet = false,
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  quiet?: boolean;
  icon?: "refresh";
}) {
  return (
    <button
      type="button"
      className={quiet ? "tt-st__btn tt-st__btn--quiet" : "tt-st__btn"}
      onClick={onClick}
    >
      {icon ? <Icon name={icon} size={18} /> : null}
      {children}
    </button>
  );
}

function Actions({ action, secondary }: { action?: ReactNode; secondary?: ReactNode }) {
  return action || secondary ? (
    <div className="tt-st__actions">
      {action}
      {secondary}
    </div>
  ) : null;
}

/** Nothing here yet: a helper, a title, one line and the next step. */
export function EmptyState({
  title = "Nothing here yet",
  body = "",
  mood = "idle",
  action,
  secondary,
}: {
  title?: string;
  body?: string;
  mood?: TiloMood;
  action?: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <div className="tt-st tt-st--empty" data-testid="tt-empty">
      <div className="tt-st__stage">
        <div className="tt-st__plot" aria-hidden="true" />
        <div className="tt-st__buddy">
          <Buddy size={128} mood={mood} />
        </div>
      </div>
      <h2 className="tt-st__title">{title}</h2>
      {body ? <p className="tt-st__body">{body}</p> : null}
      <Actions action={action} secondary={secondary} />
    </div>
  );
}

/** Something failed: what happened, what to do, and the code in mono when there is one. role="alert". */
export function ErrorState({
  title = "Something went wrong",
  body = "",
  code,
  action,
  secondary,
}: {
  title?: string;
  body?: string;
  code?: string;
  action?: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <div className="tt-st tt-st--error" role="alert" data-testid="tt-error">
      <div className="tt-st__buddy tt-st__buddy--err">
        <Buddy size={128} mood="sad" />
        <span className="tt-st__alert">
          <Icon name="alert" size={18} />
        </span>
      </div>
      <h2 className="tt-st__title">{title}</h2>
      {body ? <p className="tt-st__body">{body}</p> : null}
      <Actions action={action} secondary={secondary} />
      {code ? <span className="tt-st__code">{code}</span> : null}
    </div>
  );
}

const SEVEN: readonly (readonly [number, number, number, number])[] = [
  [90, 40, 60, 120],
  [60, 10, 120, 60],
  [140, 80, 50, 30],
  [70, 20, 90, 140],
  [110, 60, 70, 40],
  [50, 30, 40, 200],
  [80, 100, 50, 20],
];
const CHAT: readonly (readonly ["flex-end" | "flex-start", string, number])[] = [
  ["flex-end", "46%", 52],
  ["flex-start", "68%", 96],
  ["flex-start", "52%", 44],
  ["flex-end", "38%", 52],
  ["flex-start", "72%", 150],
];

const bar = (w: string, h: number, o = 1): CSSProperties => ({
  width: w,
  height: h,
  opacity: o,
});
const Bar = ({ w, h, o }: { w: string; h: number; o?: number }) => (
  <span className="tt-sk__bar" style={bar(w, h, o)} />
);
const range = (n: number) => Array.from({ length: n }, (_, i) => i);

function Skeleton({ layout }: { layout: LoadingLayout }) {
  if (layout === "list")
    return (
      <div className="tt-st__col">
        {range(6).map((i) => (
          <div key={i} className="tt-sk tt-sk--grid tt-shim tt-sk--row">
            <span className="tt-sk__ico" />
            <span className="tt-sk__lines">
              <Bar w="46%" h={11} />
              <Bar w="28%" h={9} o={0.7} />
            </span>
          </div>
        ))}
      </div>
    );
  if (layout === "split")
    return (
      <div className="tt-st__split">
        <div className="tt-st__side">
          {range(5).map((i) => (
            <div key={i} className="tt-sk tt-shim tt-sk--item" />
          ))}
        </div>
        <div className="tt-sk tt-sk--grid tt-shim tt-sk--main">
          <Bar w="30%" h={12} />
          <Bar w="70%" h={22} />
          <Bar w="55%" h={12} o={0.7} />
          <span className="tt-sk__block" />
        </div>
      </div>
    );
  if (layout === "calendar")
    return (
      <div className="tt-st__cal">
        {SEVEN.map(([h1, t1, h2, t2]) => (
          <div key={`${h1}-${t1}`} className="tt-sk tt-sk--cal tt-shim">
            <Bar w="50%" h={10} />
            <span className="tt-sk__ev" style={{ height: h1, marginTop: t1, opacity: 0.7 }} />
            <span className="tt-sk__ev" style={{ height: h2, marginTop: t2, opacity: 0.5 }} />
          </div>
        ))}
      </div>
    );
  if (layout === "world")
    return (
      <div className="tt-st__split">
        <div className="tt-sk tt-sk--plan">
          <div className="tt-sk__iso tt-sk__iso--a" />
          <div className="tt-sk__iso tt-sk__iso--b" />
          <div className="tt-sk__sheen tt-shim" />
        </div>
        <div className="tt-st__side tt-st__side--wide">
          {range(5).map((i) => (
            <div key={i} className="tt-sk tt-shim tt-sk--item tt-sk--tall" />
          ))}
        </div>
      </div>
    );
  if (layout === "chat")
    return (
      <div className="tt-st__chat">
        {CHAT.map(([al, w, h]) => (
          <div
            key={`${al}-${w}-${h}`}
            className="tt-sk tt-shim"
            style={{ alignSelf: al, width: w, height: h, borderRadius: 20 }}
          />
        ))}
      </div>
    );
  return (
    <div className="tt-st__grid">
      {range(6).map((i) => (
        <div key={i} className="tt-sk tt-sk--grid tt-shim tt-sk--card">
          <Bar w="60%" h={12} />
          <Bar w="40%" h={10} o={0.7} />
        </div>
      ))}
    </div>
  );
}

/** A skeleton in the reserved box. The caption says what is loading; role="status", aria-busy. */
export function LoadingState({
  layout = "grid",
  caption = "Loading",
}: {
  layout?: LoadingLayout;
  caption?: string;
}) {
  return (
    <div
      className="tt-st tt-st--loading"
      aria-busy="true"
      aria-live="polite"
      role="status"
      data-testid="tt-loading"
      data-layout={layout}
    >
      <div className="tt-st__pill">
        <Buddy size={36} mood="work" />
        {caption}
        <span className="tt-dots tt-st__dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </div>
      <Skeleton layout={layout} />
    </div>
  );
}
