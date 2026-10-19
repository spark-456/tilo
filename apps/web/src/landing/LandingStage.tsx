// STUDIO-6: the landing page's central stage ("Tilo S Landing", the hero city). It is a REPLAY of the recorded run in
// recordedRun.ts, labelled as a recorded example on every frame and never shown as live work (HR-4). It moves one
// recorded event at a time: each step swaps in the next frame of the record, with no tween, transition or idle
// motion (HR-1..3), and it stops at the record's end. The person can pause it (WCAG 2.2.2). With reduced motion it
// shows the record's last frame, still. The whole record is readable as text below it (screen-reader Story).
import { type ReactNode, useEffect, useState } from "react";
import { cityArt, helperArt } from "./landingKit";
import { usePrefersReducedMotion } from "./media";
import { RECORDED_RUN, type StoryLine } from "./recordedRun";

/** How long each recorded event stays on the stage before the next one (the replay is faster than the record). */
export const STEP_MS = 650;

const TONE: Readonly<Record<StoryLine["tone"], string | null>> = {
  gate: "Asks you",
  yes: "Your yes",
  info: null,
};

function Face({ line, night }: { line: StoryLine; night: boolean }): ReactNode {
  if (line.rank) return helperArt({ rank: line.rank, expr: "neutral" }, 34, night);
  return <span className="landing-stage__initial">{line.who === "You" ? "Y" : "t"}</span>;
}

export default function LandingStage({ night }: { readonly night: boolean }) {
  const reduced = usePrefersReducedMotion();
  const { frames } = RECORDED_RUN;
  const last = frames.length - 1;
  const [step, setStep] = useState(1);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (reduced || !playing) return;
    if (step >= last) {
      setPlaying(false);
      return;
    }
    // one recorded event per step, scheduled one at a time (no repeating timer, nothing between events)
    const t = window.setTimeout(() => setStep((s) => Math.min(s + 1, last)), STEP_MS);
    return () => window.clearTimeout(t);
  }, [reduced, playing, step, last]);

  const shown = reduced ? last : step;
  const frame = frames[shown] ?? frames[last];
  if (!frame) return null;
  const ended = shown >= last;
  const control = ended ? "Replay again" : playing ? "Pause replay" : "Play replay";
  const onControl = () => {
    if (ended) {
      setStep(1);
      setPlaying(true);
    } else setPlaying(!playing);
  };

  return (
    <figure
      className="landing-stage"
      data-testid="landing-stage"
      data-step={shown}
      data-static={reduced ? "true" : undefined}
      aria-labelledby="landing-stage-label"
    >
      <figcaption className="landing-stage__label" id="landing-stage-label">
        <span className="landing-stage__tag">Recorded example</span>
        <span data-testid="landing-stage-note">
          {reduced
            ? "The end of a recorded sample run, shown still. Nothing here is live."
            : "A recorded sample run, replayed faster than it happened. Nothing here is live."}
        </span>
      </figcaption>

      <div className="landing-stage__city" aria-hidden="true">
        {frame.plan ? cityArt(frame.plan) : null}
      </div>

      <div className="landing-stage__ask">
        <span className="landing-mono">YOU ASKED</span>
        <span className="landing-stage__asked">{frame.ask ?? ""}</span>
      </div>

      <ol className="landing-stage__lines">
        {frame.lines.map((line) => (
          <li key={line.seq} className={`landing-stage__line landing-stage__line--${line.tone}`}>
            <span className="landing-stage__face" aria-hidden="true">
              <Face line={line} night={night} />
            </span>
            <span className="landing-stage__said">
              <span className="landing-stage__who">
                {line.who}
                {TONE[line.tone] ? (
                  <span className="landing-stage__tone"> · {TONE[line.tone]}</span>
                ) : null}
              </span>
              <span>{line.text}</span>
            </span>
          </li>
        ))}
      </ol>

      {frame.done ? (
        <div className="landing-stage__done" data-testid="landing-stage-done">
          <span className="landing-mono">DONE · RECORDED</span>
          <strong>{frame.done}</strong>
        </div>
      ) : null}

      <div className="landing-stage__foot">
        <div className="landing-stage__progress">
          <div className="landing-stage__count">
            <span>
              Recorded event {shown} of {last}
            </span>
            {reduced ? null : (
              <button type="button" className="landing-link-btn" onClick={onControl}>
                {control}
              </button>
            )}
          </div>
          <div className="landing-stage__track" aria-hidden="true">
            <span style={{ width: `${Math.round((shown / last) * 100)}%` }} />
          </div>
        </div>
        <span className="landing-stage__helper" aria-hidden="true">
          {helperArt({ rank: "director", expr: frame.done ? "delighted" : "neutral" }, 96, night)}
        </span>
      </div>
    </figure>
  );
}

/** The whole record as text (the screen-reader Story of the stage), under the stage's fixed box. */
export function RecordedStory() {
  return (
    <details className="landing-story">
      <summary>Read the whole recorded run as text</summary>
      <ol>
        {RECORDED_RUN.events.map((e) => (
          <li key={e.seq}>{e.summary}</li>
        ))}
      </ol>
    </details>
  );
}
