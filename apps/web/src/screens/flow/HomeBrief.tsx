// S-01 top line (artboard Tilo Home v2): the decisions banner when the run has some waiting, else a
// greeting. One fixed-height slot holds either, so a decision arriving moves nothing (UX-1, CLS).
// The banner reads the same queue S-06 lists (HR-1). The greeting is the time of day on this
// device and nothing else: the client has no signed-in person, so it never names one (BQ in
// docs/open-questions.md).
import { useClient } from "../../api/ClientProvider";
import { deriveQueue } from "../../needs-you/queue";
import { useRunLog } from "../../world/runLog";
import { withWorld } from "../../world/worldContext";
import { AppLink } from "../AppLink";
import { useCountedWorld } from "../PrimaryNav";
import { worldTitle } from "../TopBar";
import { plural } from "../kit";

export const greeting = (hour: number): string =>
  hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";

export function HomeBrief() {
  const counted = useCountedWorld();
  const events = useRunLog(useClient(), counted);
  const queue = deriveQueue(events);
  const title = worldTitle(events);
  const n = queue.length;
  return (
    <div className="home-brief" data-tone={n > 0 ? "needs" : "calm"} data-testid="home-brief">
      {n > 0 && counted !== null ? (
        <>
          <div className="brief-text">
            <p className="brief-title">
              {n === 1 ? "1 decision is" : `${plural(n, "decision")} are`} waiting
              {title ? ` in ${title}` : ""}
            </p>
            <p className="brief-sub">{queue.map((q) => q.opened.summary).join(" · ")}</p>
          </div>
          <AppLink to={withWorld("/needs-you", counted)} className="brief-review">
            Review
          </AppLink>
        </>
      ) : (
        <p className="brief-greeting">{greeting(new Date().getHours())}</p>
      )}
    </div>
  );
}
