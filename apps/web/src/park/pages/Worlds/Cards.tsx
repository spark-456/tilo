// The three world cards of the Worlds page: a city (404 high), a town (196) and a village (150). Each is a
// real link to the world; a plain click goes through the shell (`onOpen`), a modified click keeps the browser's.
import type { MouseEvent, ReactNode } from "react";
import type { World } from "../../api/types";
import { parkPath } from "../../app/router";
import { cx } from "../../components/cx";
import type { Art } from "./art";
import type { Status } from "./model";

export interface CardProps {
  w: World;
  art: Art;
  status: Status;
  onOpen: (worldId: string) => void;
}

const edge = (w: World): string | false =>
  w.st === "needs" ? "park-worlds-card--needs" : w.isNew === true && "park-worlds-card--new";

function linkProps(w: World, onOpen: CardProps["onOpen"]) {
  return {
    href: parkPath("world", { id: w.id }),
    onClick: (e: MouseEvent<HTMLAnchorElement>) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      onOpen(w.id);
    },
  };
}

function Chip({ status, abs }: { status: Status; abs?: boolean }) {
  return (
    <span
      className={cx(
        "park-worlds-chip",
        status.tone === "needs" && "park-worlds-chip--needs",
        abs && "park-worlds-chip--abs",
      )}
    >
      <span className={`park-worlds-dot park-worlds-dot--${status.tone}`} />
      {status.label}
    </span>
  );
}

function Fill({ w, status, round }: { w: World; status: Status; round?: boolean }) {
  return (
    <div
      className={cx(
        "park-worlds-fill",
        `park-worlds-fill--${status.tone}`,
        round && "park-worlds-fill--round",
      )}
      style={{ width: `${w.prog ?? 0}%` }}
    />
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="park-worlds-stat">
      <span className="park-worlds-stat__label">{label}</span>
      <span className="park-worlds-stat__value">{children}</span>
    </div>
  );
}

export function CityCard({ w, art, status, onOpen }: CardProps) {
  return (
    <a className={cx("park-worlds-card park-worlds-card--city", edge(w))} {...linkProps(w, onOpen)}>
      <div className="park-worlds-city__head">
        <div className="park-worlds-city__titles">
          <div className="park-worlds-tool">{w.tool.toUpperCase()}</div>
          <div className="park-worlds-city__name">{w.name}</div>
          <div className="park-worlds-city__meta">{w.meta ?? ""}</div>
        </div>
        <Chip status={status} />
      </div>
      <div className="park-worlds-city__art">{art.city(w)}</div>
      <div className="park-worlds-city__progress">
        <div className="park-worlds-track">
          <Fill w={w} status={status} round />
        </div>
        <span className="park-worlds-pct">{w.prog != null ? `${w.prog}%` : "—"}</span>
      </div>
      <div className="park-worlds-stats">
        <Stat label="Spend">
          {w.spend} <span className="park-worlds-stat__of">{w.of ?? ""}</span>
        </Stat>
        <Stat label="Agents">{String(w.agents)}</Stat>
        <Stat label={w.nextL}>{w.nextV}</Stat>
      </div>
    </a>
  );
}

export function TownCard({ w, art, status, onOpen }: CardProps) {
  return (
    <a className={cx("park-worlds-card park-worlds-card--town", edge(w))} {...linkProps(w, onOpen)}>
      <div className="park-worlds-town__strip">{art.strip(w)}</div>
      <Chip status={status} abs />
      <div className="park-worlds-town__body">
        <div className="park-worlds-tool">{w.tool.toUpperCase()}</div>
        <div className="park-worlds-town__name">{w.name}</div>
        <div className="park-worlds-town__meta">{w.meta ?? ""}</div>
        <div className="park-worlds-town__spacer" />
        <div className="park-worlds-town__next">
          <span className="park-worlds-town__when">
            {w.nextL} {w.nextV}
          </span>
          <span className="park-worlds-town__spend">
            {w.spend} {w.of ?? ""}
          </span>
        </div>
      </div>
      {w.prog != null ? (
        <div className="park-worlds-town__track">
          <Fill w={w} status={status} />
        </div>
      ) : null}
    </a>
  );
}

export function VillageCard({ w, art, status, onOpen }: CardProps) {
  return (
    <a
      className={cx("park-worlds-card park-worlds-card--village", edge(w))}
      {...linkProps(w, onOpen)}
    >
      <div className="park-worlds-village__top">
        <div className="park-worlds-village__tile">{art.single(w)}</div>
        <Chip status={status} />
      </div>
      <div className="park-worlds-village__name">{w.name}</div>
      <div className="park-worlds-village__when">{w.when || `${w.nextL} ${w.nextV}`}</div>
    </a>
  );
}
