// The world card of the Worlds page (STUDIO-3, "Tilo S Worlds.dc.html"): the world's own picture with its status
// pill and progress, then its name, the list's next or last line, a progress bar, its helpers and its spend. Each
// card is a real link to the world; a plain click goes through the shell (`onOpen`), a modified click keeps the
// browser's. Every value is the list item's own; a sample world says so and a teammate's world says it is shared.
import { type MouseEvent, memo } from "react";
import type { World } from "../../api/types";
import { parkPath } from "../../app/router";
import { cx } from "../../components/cx";
import { SampleBadge, SampleNote } from "../../sample/SampleBadge";
import { WorldThumbnail, type WorldThumbnailClient } from "../../shared/WorldThumbnail";
import { Pin, PinOff, Trash2 } from "../../shared/icons";
import type { Art } from "./art";
import { type Status, lastLine, plural } from "./model";

export interface CardProps {
  w: World;
  art: Art;
  status: Status;
  client: WorldThumbnailClient | null;
  night: boolean;
  onOpen: (worldId: string) => void;
  /** WORLDS-MANAGE: pinned to the top of the list (this browser's choice). */
  pinned?: boolean;
  onPin?: (worldId: string) => void;
  /** Present only for a world the person may delete (their own, not the sample). */
  onDelete?: (worldId: string) => void;
  /** Selection mode: a click picks the card instead of opening it. */
  selecting?: boolean;
  selected?: boolean;
  onPick?: (worldId: string) => void;
}

function linkProps(w: World, onOpen: CardProps["onOpen"], pick?: () => void) {
  return {
    href: parkPath("world", { id: w.id }),
    // The card is one link: the world's name is its name, not the sum of its stats.
    "aria-label": w.name,
    onClick: (e: MouseEvent<HTMLAnchorElement>) => {
      if (pick) {
        // Selection mode: the card is picked, never opened.
        e.preventDefault();
        pick();
        return;
      }
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      onOpen(w.id);
    },
  };
}

function WorldCardView({
  w,
  status,
  client,
  night,
  onOpen,
  pinned = false,
  onPin,
  onDelete,
  selecting = false,
  selected = false,
  onPick,
}: CardProps) {
  const pct = w.prog != null ? `${w.prog}%` : "—";
  const pick = selecting && onPick && onDelete ? () => onPick(w.id) : undefined;
  return (
    <div
      className={cx(
        "park-worlds-cardwrap",
        pinned && "park-worlds-cardwrap--pinned",
        selected && "park-worlds-cardwrap--picked",
      )}
    >
      <a
        className={cx(
          "park-worlds-card",
          `park-worlds-card--${w.tier.toLowerCase()}`,
          w.st === "needs" && "park-worlds-card--needs",
        )}
        {...linkProps(w, onOpen, pick)}
      >
        <div className="park-worlds-card__art">
          <div className="park-worlds-card__pic">
            <WorldThumbnail world={w} client={w.sample ? null : client} night={night} />
          </div>
          <span className={cx("park-worlds-chip", `park-worlds-chip--${status.tone}`)}>
            <span className={`park-worlds-dot park-worlds-dot--${status.tone}`} />
            {status.label}
          </span>
          <span className="park-worlds-pct">{pct}</span>
        </div>
        <div className="park-worlds-card__body">
          <div className="park-worlds-card__titles">
            <div className="park-worlds-card__name-row">
              <span className="park-worlds-card__name">{w.name}</span>
              {w.sample ? <SampleBadge /> : null}
              {w.access === "team" ? <span className="park-worlds-team">Team</span> : null}
            </div>
            <span className="park-worlds-card__last">
              {w.sample ? <SampleNote /> : lastLine(w)}
            </span>
          </div>
          <div className="park-worlds-track">
            <div
              className={`park-worlds-fill park-worlds-fill--${status.tone}`}
              style={{ width: `${w.prog ?? 0}%` }}
            />
          </div>
          <div className="park-worlds-card__foot">
            {/* The list API omits agents; use a dash instead of inventing zero. */}
            {w.agents > 0 ? (
              <span className="park-worlds-card__agents">
                {`${w.tier} · ${plural(w.agents, "helper", "helpers")}`}
              </span>
            ) : (
              <span className="park-worlds-card__agents">Helpers —</span>
            )}
            {w.spend ? (
              <span className="park-worlds-card__cost">
                {[w.spend, w.of].filter(Boolean).join(" ")}
              </span>
            ) : null}
          </div>
        </div>
      </a>
      {selecting && onDelete && onPick ? (
        <label className="park-worlds-pick">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onPick(w.id)}
            aria-label={`Select ${w.name}`}
          />
        </label>
      ) : (
        <div className="park-worlds-cardtools">
          {onPin ? (
            <button
              type="button"
              className={cx("park-worlds-tool", pinned && "park-worlds-tool--on")}
              aria-label={pinned ? `Unpin ${w.name}` : `Pin ${w.name} to the top`}
              title={pinned ? "Unpin" : "Pin to the top"}
              onClick={() => onPin(w.id)}
            >
              {pinned ? (
                <PinOff size={16} aria-hidden="true" />
              ) : (
                <Pin size={16} aria-hidden="true" />
              )}
            </button>
          ) : null}
          {onDelete ? (
            <button
              type="button"
              className="park-worlds-tool park-worlds-tool--delete"
              aria-label={`Delete ${w.name}`}
              title="Delete"
              onClick={() => onDelete(w.id)}
            >
              <Trash2 size={16} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

// Memoised: the page draws its cards one task at a time (WEB-MOTION-2), and a card already drawn must not be
// rendered again, art and all, each time the next one is added.
export const WorldCard = memo(WorldCardView);
