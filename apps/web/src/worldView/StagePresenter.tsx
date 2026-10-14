// FR-WLD-12 (PRD 9.6, 18.3): Stage mode presenter controls and the reset confirmation dialog. Fixed over the corner
// so it never shifts the layout (CLS 0). Reset asks for confirmation first with nothing pre-chosen, and only clears
// demo display state on confirm (HR-1).
import type { Event } from "@tilo/contracts";
import { useEffect, useRef } from "react";
import { useClient } from "../api/ClientProvider";
import {
  askResetStageDemo,
  cancelResetStageDemo,
  confirmResetStageDemo,
  handlePresenterHotkey,
  setStageMode,
  useResetConfirm,
  useStageMode,
} from "../display/stageMode";
import { useRunLog } from "../world/runLog";
import { runEnded, worldStatus } from "../world/runSummary";

export function StagePresenter({
  worldId,
  fixtureEvents,
  fixtureFinished,
}: {
  readonly worldId: string | null;
  readonly fixtureEvents?: readonly Event[];
  readonly fixtureFinished?: boolean;
}) {
  const client = useClient();
  const loggedEvents = useRunLog(client, fixtureEvents ? null : worldId);
  const events = fixtureEvents ?? loggedEvents;
  const finished = fixtureFinished ?? (events.length > 0 && runEnded(worldStatus(events)));
  const [stageMode] = useStageMode();
  const confirmOpen = useResetConfirm();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const openBtnRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      handlePresenterHotkey(e, { worldId, events, finished });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [worldId, events, finished]);

  useEffect(() => {
    if (confirmOpen) {
      wasOpenRef.current = true;
      headingRef.current?.focus();
    } else if (wasOpenRef.current) {
      wasOpenRef.current = false;
      openBtnRef.current?.focus();
    }
  }, [confirmOpen]);

  return (
    <>
      {stageMode ? (
        <aside
          className="park-view-presenter"
          data-testid="stage-presenter"
          aria-label="Stage mode controls"
        >
          <span className="park-view-flag park-view-flag--info" data-testid="stage-mode-badge">
            Stage mode
          </span>
          <button
            ref={openBtnRef}
            type="button"
            className="park-view-chiplink"
            data-testid="stage-reset-open"
            data-stage-control
            onClick={askResetStageDemo}
          >
            Reset demo
          </button>
          <button
            type="button"
            className="park-view-chiplink"
            data-testid="stage-mode-exit"
            data-stage-control
            onClick={() => setStageMode(false)}
          >
            Exit stage
          </button>
        </aside>
      ) : null}
      {confirmOpen ? (
        <dialog
          open
          className="park-view-dialog"
          data-testid="stage-reset-dialog"
          aria-modal="true"
          aria-labelledby="stage-reset-title"
        >
          <h2 id="stage-reset-title" tabIndex={-1} ref={headingRef}>
            Reset demo?
          </h2>
          <p>
            Clears the current selection, replay scrub position and display settings for this demo.
            Recorded run events are not changed.
          </p>
          <div className="park-view-dialogactions">
            <button
              type="button"
              className="park-view-chiplink park-view-danger"
              data-testid="stage-reset-confirm"
              data-stage-control
              onClick={() => confirmResetStageDemo(worldId)}
            >
              Reset demo
            </button>
            <button
              type="button"
              className="park-view-chiplink"
              data-testid="stage-reset-cancel"
              data-stage-control
              onClick={cancelResetStageDemo}
            >
              Keep demo as it is
            </button>
          </div>
        </dialog>
      ) : null}
    </>
  );
}
