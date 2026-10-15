// The world card of the Worlds page (STUDIO-3, "Tilo S Worlds.dc.html"): the world's own picture with its status
// pill and progress, then its name, the list's next or last line, a progress bar, its helpers and its spend. Each
// card is a real link to the world; a plain click goes through the shell (`onOpen`), a modified click keeps the
// browser's. Every value is the list item's own; a sample world says so and a teammate's world says it is shared.
import { type MouseEvent, memo } from "react";
import type { World } from "../../api/types";
import { parkPath } from "../../app/router";
import { useAfterTask } from "../../app/useStaged";
import { cx } from "../../components/cx";
import { SampleBadge, SampleNote } from "../../sample/SampleBadge";
import type { Art } from "./art";
import { type Status, lastLine, plural } from "./model";

export interface CardProps {
  w: World;
  art: Art;
  status: Status;
  onOpen: (worldId: string) => void;
}

function linkProps(w: World, onOpen: CardProps["onOpen"]) {
  return {
    href: parkPath("world", { id: w.id }),
    // The card is one link: the world's name is its name, not the sum of its stats.
    "aria-label": w.name,
    onClick: (e: MouseEvent<HTMLAnchorElement>) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      onOpen(w.id);
    },
  };
}

/** The picture by size: a city's plan, a town's building row or a village's one building (frozen frames). */
function Picture({ w, art }: { w: World; art: Art }) {
  const artOn = useAfterTask(); // a city's picture is the heavy part: drawn a task after the card (WEB-MOTION-2)
  if (w.tier === "City") return artOn ? <>{art.city(w)}</> : null;
  if (w.tier === "Town") return <>{art.strip(w)}</>;
  return <>{art.single(w)}</>;
}

function WorldCardView({ w, art, status, onOpen }: CardProps) {
  const pct = w.prog != null ? `${w.prog}%` : "—";
  return (
    <a
      className={cx(
        "park-worlds-card",
        `park-worlds-card--${w.tier.toLowerCase()}`,
        w.st === "needs" && "park-worlds-card--needs",
      )}
      {...linkProps(w, onOpen)}
    >
      <div className="park-worlds-card__art">
        <div className="park-worlds-card__pic">
          <Picture w={w} art={art} />
        </div>
        <span className={cx("park-worlds-chip", `park-worlds-chip--${status.tone}`)}>
          <span className={`park-worlds-dot park-worlds-dot--${status.tone}`} />
          {status.label}
        </span>
        <span className="park-worlds-pct">{pct}</span>
      </div>
      <div className="park-worlds-card__body">
        <div className="park-worlds-card__titles">
          <span className="park-worlds-card__name">
            {w.name}
            {w.sample ? <SampleBadge /> : null}
            {w.access === "team" ? <span className="park-worlds-team">Team</span> : null}
          </span>
          <span className="park-worlds-card__last">{w.sample ? <SampleNote /> : lastLine(w)}</span>
        </div>
        <div className="park-worlds-track">
          <div
            className={`park-worlds-fill park-worlds-fill--${status.tone}`}
            style={{ width: `${w.prog ?? 0}%` }}
          />
        </div>
        <div className="park-worlds-card__foot">
          {/* The live list serves no agent count or spend: nothing is printed rather than a zero (HR-1). */}
          <span>
            {w.agents > 0 ? `${w.tier} · ${plural(w.agents, "helper", "helpers")}` : w.tier}
          </span>
          {w.spend ? (
            <span className="park-worlds-card__cost">
              {[w.spend, w.of].filter(Boolean).join(" ")}
            </span>
          ) : null}
        </div>
      </div>
    </a>
  );
}

// Memoised: the page draws its cards one task at a time (WEB-MOTION-2), and a card already drawn must not be
// rendered again, art and all, each time the next one is added.
export const WorldCard = memo(WorldCardView);
