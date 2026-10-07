// The world loader (README "Interactions and motion": Open a world; reference `Tilo App.dc.html` wlOn): a
// scrim with a 400px card (the world's art, "OPENING CITY", name, meta, three steps and a 4px bar). The steps
// tick from a ring to a green check as the store's loader advances (the ring spins with tiloSpin); the page
// swaps in at step 3 and the card fades out over 280 ms on the next tick (`leaving`: the stylesheet fades the
// scrim, the browser's animationend calls `onGone`). The bar jumps to its width.
import type { ReactNode } from "react";
import { worlds } from "../api/fixtures/worlds";
import type { Dec, TierName, World } from "../api/types";
import type { WorldLaunch } from "../app/store";
import { ArtTile, ModalScrim } from "../components";
import { icon, parkKit } from "./kit";

const STEPS: Record<TierName, (agents: number) => [string, string, string]> = {
  City: (n) => [
    "Loading districts and buildings",
    `Waking ${n} agents`,
    "Syncing spend and decisions",
  ],
  Town: () => ["Loading the routine", "Reading run history", "Checking the next run"],
  Village: () => ["Loading the task", "Checking progress", "Fetching results"],
};

function art(world: World, night: boolean): ReactNode {
  const kit = parkKit();
  const drawn =
    world.tier === "City"
      ? kit.agent({ rank: "director", expr: "focused" }, 50, night)
      : kit.art(world, 50, night);
  return drawn as ReactNode;
}

/** The step marker: a check when done, a ring on the current step, nothing after it. */
function mark(i: number, step: number): ReactNode {
  if (i < step) return icon("check", 12);
  if (i === step) return <span className="park-shell__ring" />;
  return null;
}

export function WorldLoader({
  launch,
  dec,
  added,
  night,
  leaving,
  onGone,
}: {
  launch: WorldLaunch;
  dec: Dec;
  added: readonly World[];
  night: boolean;
  /** The last step is done and the card is fading out. */
  leaving?: boolean;
  /** The fade is over (the browser's animationend). */
  onGone?: () => void;
}) {
  const world = worlds(dec, added).find((w) => w.id === launch.id);
  if (!world) return null;
  const { step } = launch;
  const agents = world.agents === 1 ? "agent" : "agents";
  return (
    // The wrapper only catches the scrim's animationend (it bubbles up); it draws nothing.
    <div className="park-shell__wl" onAnimationEnd={leaving ? onGone : undefined}>
      <ModalScrim status>
        <div className={`park-shell__card ${leaving ? "park-shell__card--leaving" : ""}`}>
          <div className="park-shell__cardhead">
            <ArtTile size={58} radius={16}>
              {art(world, night)}
            </ArtTile>
            <div className="park-shell__cardtext">
              <div className="park-shell__eyebrow">{`Opening ${world.tier}`.toUpperCase()}</div>
              <div className="park-shell__cardname">{world.name}</div>
              <div className="park-shell__cardmeta">{`${world.tool} · ${world.agents} ${agents}`}</div>
            </div>
          </div>
          <div className="park-shell__steps">
            {STEPS[world.tier](world.agents).map((label, i) => (
              <div
                key={label}
                className={`park-shell__step ${i <= step ? "park-shell__step--on" : ""}`}
              >
                <span
                  className={`park-shell__mark ${
                    i < step ? "park-shell__mark--done" : i === step ? "" : "park-shell__mark--next"
                  }`}
                >
                  {mark(i, step)}
                </span>
                {label}
              </div>
            ))}
          </div>
          <div className="park-shell__lbar">
            <div
              className="park-shell__lfill"
              style={{ width: `${Math.min(100, (step + 1) * 30)}%` }}
            />
          </div>
        </div>
      </ModalScrim>
    </div>
  );
}
