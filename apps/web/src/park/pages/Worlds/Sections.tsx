// The three sized sections of the Worlds page (a heading with its size glyph and count, then a grid of
// cards) and the dashed empty box.
import type { ReactNode } from "react";
import { cx } from "../../components/cx";

export type Scale = "City" | "Town" | "Village";

const COPY: Record<Scale, { title: string; blurb: string; lit: number }> = {
  City: { title: "Cities", blurb: "big projects with districts and gates", lit: 3 },
  Town: { title: "Towns", blurb: "routines and small projects", lit: 2 },
  Village: { title: "Villages", blurb: "quick tasks, done in minutes", lit: 1 },
};

export function Section({
  scale,
  count,
  children,
}: { scale: Scale; count: number; children: ReactNode }) {
  const { title, blurb, lit } = COPY[scale];
  return (
    <section aria-label={title} className="park-worlds-section">
      <div className="park-worlds-section__head">
        <span className="park-worlds-bars" aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <span
              key={n}
              className={cx(
                "park-worlds-bar",
                `park-worlds-bar--${n}`,
                n > lit && "park-worlds-bar--dim",
              )}
            />
          ))}
        </span>
        <span className="park-worlds-section__title">{title}</span>
        <span className="park-worlds-section__count">{`${count} · ${blurb}`}</span>
      </div>
      <div className={`park-worlds-grid park-worlds-grid--${scale.toLowerCase()}`}>{children}</div>
    </section>
  );
}

export function EmptyBox({ title, body }: { title: string; body?: string }) {
  return (
    <div className="park-worlds-empty">
      <div className="park-worlds-empty__title">{title}</div>
      {body ? <div className="park-worlds-empty__body">{body}</div> : null}
    </div>
  );
}
