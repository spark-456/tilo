// "Waiting for you" (the amber box with one card per decision) and the "all caught up" banner.
import type { Dec, Decision, DecisionKey } from "../../api/types";
import { cx } from "../../components/cx";
import type { Art } from "./art";
import { plural } from "./model";

interface SpotlightProps {
  art: Art;
  decisions: readonly Decision[];
  /** The name of the world the decisions wait on (data, not a literal). */
  worldName: string;
  dec: Dec;
  needsLeft: number;
  onDecide: (key: DecisionKey) => void;
  onOpen: (worldId: string) => void;
}

function DecisionCard({
  art,
  d,
  done,
  onDecide,
  onOpen,
}: { art: Art; d: Decision; done: boolean } & Pick<SpotlightProps, "onDecide" | "onOpen">) {
  return (
    <div className="park-worlds-dec">
      <div className="park-worlds-dec__row">
        <div className={cx("park-worlds-dec__tile", done && "park-worlds-dec__tile--done")}>
          {art.icon(done ? "check" : d.icon, 17)}
        </div>
        <div className="park-worlds-dec__text">
          <div className="park-worlds-dec__title">{d.title}</div>
          <div className="park-worlds-dec__body">{d.body}</div>
        </div>
      </div>
      {done ? (
        <div className="park-worlds-dec__done">
          {art.icon("check", 14)}
          {d.done}
        </div>
      ) : (
        <div className="park-worlds-dec__actions">
          <button type="button" className="park-worlds-dec__yes" onClick={() => onDecide(d.k)}>
            {d.yes}
          </button>
          <button type="button" className="park-worlds-dec__open" onClick={() => onOpen(d.world)}>
            Open in world
          </button>
        </div>
      )}
    </div>
  );
}

export function Spotlight({
  art,
  decisions,
  worldName,
  dec,
  needsLeft,
  onDecide,
  onOpen,
}: SpotlightProps) {
  if (needsLeft === 0)
    return (
      <div className="park-worlds-clear">
        <div className="park-worlds-clear__tile">{art.icon("check", 18)}</div>
        <div className="park-worlds-clear__text">
          <div className="park-worlds-clear__title">You’re all caught up</div>
          <div className="park-worlds-clear__body">
            {worldName} is moving again. Tilo will ask if anything else needs you.
          </div>
        </div>
      </div>
    );
  return (
    <div className="park-worlds-spot">
      <div className="park-worlds-spot__lead">
        <div className="park-worlds-spot__agent">{art.agent()}</div>
        <div className="park-worlds-spot__text">
          <div className="park-worlds-spot__label">WAITING FOR YOU</div>
          <div className="park-worlds-spot__world">{worldName}</div>
          <div className="park-worlds-spot__paused">
            {plural(needsLeft, "building paused", "buildings paused")}
          </div>
        </div>
      </div>
      {decisions.map((d) => (
        <DecisionCard
          key={d.k}
          art={art}
          d={d}
          done={Boolean(dec[d.k])}
          onDecide={onDecide}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}
