// TILO-T-WORLD: Pause, 1x, 2x and Catch up for a finished world's replay. Triggered by the person pressing a speed; each
// step shows the next recorded event (the stage draws stateAt(point), Story and Chat read the same slice).
import { useEffect, useState } from "react";
import { useClient } from "../../api/ClientProvider";
import { Icon } from "../../design/tilo-t";
import { indexToPoint, pointToIndex, setReplayPoint, useReplayPoint } from "../../world/replay";
import { useRunLog } from "../../world/runLog";
import { runEnded, worldStatus } from "../../world/runSummary";
import { STEP_MS, type Speed, afterStep } from "./playback";
import "./live.css";

const LABEL: Readonly<Record<Speed, string>> = {
  paused: "Pause",
  "1x": "1×",
  "2x": "2×",
  catch: "Catch up",
};

export function PlaybackBar({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const point = useReplayPoint(worldId);
  const [speed, setSpeed] = useState<Speed>("paused");
  const finished = runEnded(worldStatus(events));
  const last = events.length;
  const index = pointToIndex(events, point);

  useEffect(() => {
    if (speed === "paused" || !finished) return;
    const timer = setTimeout(() => {
      const next = afterStep(speed, index, last);
      setReplayPoint(worldId, indexToPoint(events, next.index));
      setSpeed(next.speed);
    }, STEP_MS[speed]);
    return () => clearTimeout(timer);
  }, [speed, index, last, finished, events, worldId]);

  if (!finished || last === 0) return null;
  const start = (to: Speed) => {
    // From the end (the whole run shown) a speed replays from the start; otherwise it carries on from here.
    if (to !== "paused" && index >= last) setReplayPoint(worldId, 0);
    setSpeed(to);
  };

  const evT = last;
  const evN = point === null ? last : Math.max(1, Math.min(index + 1, last));
  const evItem = events[evN - 1] ?? events[0];
  const evName = evItem?.type ?? "idle";
  const scrubPct = evT > 0 ? Math.round((evN / evT) * 100) : 0;

  return (
    <fieldset className="tw-play" aria-label="Replay speed">
      {(Object.keys(LABEL) as Speed[]).map((s) => (
        <button
          key={s}
          type="button"
          aria-pressed={speed === s}
          aria-label={s === "paused" ? (speed === "paused" ? "Play replay" : "Pause replay") : LABEL[s]}
          className="tw-play__b"
          onClick={() => {
            if (s === "paused") {
              if (speed === "paused") {
                start("1x");
              } else {
                start("paused");
              }
            } else {
              start(s);
            }
          }}
        >
          {s === "paused" ? (
            <Icon name={speed === "paused" ? "play" : "pause"} size={16} />
          ) : s === "catch" ? (
            <Icon name="bolt" size={16} />
          ) : null}
          {s === "paused" ? "Play / Pause" : LABEL[s]}
        </button>
      ))}
      <button
        type="button"
        className="tw-play__b"
        onClick={() => {
          if (point !== null) {
            setSpeed("paused");
            setReplayPoint(worldId, null);
          } else {
            setReplayPoint(worldId, 0);
            setSpeed("1x");
          }
        }}
      >
        Whole run
      </button>
      <div className="tw-play__scrubber" data-testid="playback-scrubber">
        <div className="tw-play__track">
          <div
            className="tw-play__fill"
            style={{ width: `${scrubPct}%` }}
          />
        </div>
        <span className="tw-play__meta">
          {`event ${evN} of ${evT} · ${evName}`}
        </span>
      </div>
    </fieldset>
  );
}
