// WORLD-LIVE: the delivery spot of a real run's World page and the readable Result panel. Under the map there is
// always a labelled "Delivery Dock" line: it says plainly that nothing has been delivered, or that the result is ready
// and offers it. When the run records its delivery while the page is open (artifact.delivered, then world.completed)
// the Result panel opens by itself: the result's title, a short summary, the output itself, and Open, Copy and
// Download. Every word is the run's own output or a recorded state (HR-1); a result that is a file says so.
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import type { Api } from "../../api";
import { openResult, saveResult } from "../../api/results";
import { focusablesIn, handleSlackDialogKeyDown } from "../../app/slackShare";
import { Button } from "../../components";
import { Markdown } from "./markdown";
import { runView } from "./runView";
import type { RunEvent } from "./useRunEvents";
import { type ResultView, useRunResult } from "./useRunResult";

const SUMMARY_MAX = 220;

const plain = (line: string): string =>
  line
    .replace(/^[#>*\-\s]+/, "")
    .replace(/[*_`]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .trim();

/** The result's own title (its first heading) and a short summary (its first line of prose), else the world's name. */
export function resultHeadline(
  text: string,
  fallbackTitle: string,
): { title: string; summary: string } {
  const lines = text.split(/\r?\n/).map((l) => l.trim());
  const heading = lines.find((l) => /^#{1,3}\s+\S/.test(l));
  const prose = lines.find((l) => l !== "" && !/^#{1,6}\s/.test(l) && !/^[-*_]{3,}$/.test(l));
  const title = heading ? plain(heading) : fallbackTitle;
  const summary = prose ? plain(prose) : "";
  return {
    title: title || fallbackTitle,
    summary:
      summary.length > SUMMARY_MAX ? `${summary.slice(0, SUMMARY_MAX - 1).trimEnd()}…` : summary,
  };
}

function Body({ view }: { view: ResultView }) {
  if (view.status === "loading") return <p className="park-world-noruns">Loading the result…</p>;
  if (view.status === "error")
    return (
      <p className="park-world-noruns" role="alert">
        The result could not be loaded. Nothing is lost.
      </p>
    );
  if (view.status === "file")
    return (
      <p className="park-world-noruns">
        {`The result is a file (${view.blob.type || "unknown type"}). Open or download it to read it.`}
      </p>
    );
  if (view.status !== "text") return null;
  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling text box must be reachable by keyboard to be read
    <div className="park-world-resulttext park-world-resultpanel-text" tabIndex={0}>
      {view.kind === "markdown" ? (
        <Markdown text={view.text} />
      ) : (
        <pre className="park-world-resultpre">{view.text}</pre>
      )}
      {view.cut ? (
        <p className="park-world-sub">Showing the start. Download it for the rest.</p>
      ) : null}
    </div>
  );
}

/** One read of the run's result, shared by the Delivery Dock, its panel and the Result tab (one request, one answer,
 * one Try again). Nothing is read until the run is recorded as delivered (artifact.delivered and world.completed). */
export interface SharedResult {
  readonly view: ResultView;
  readonly retry: () => void;
}

export function useSharedResult(
  api: Api,
  worldId: string | null,
  events: readonly RunEvent[],
): SharedResult {
  const [attempt, setAttempt] = useState(0);
  const delivered = worldId !== null && events.length > 0 && runView(events).deliverable;
  const view = useRunResult(api, worldId ?? "", delivered, attempt);
  return { view, retry: () => setAttempt((n) => n + 1) };
}

export function DeliveryDock({
  result,
  worldId,
  worldName,
  delivered,
  failed,
}: {
  result: SharedResult;
  worldId: string;
  worldName: string;
  /** artifact.delivered and world.completed are both recorded. */
  delivered: boolean;
  failed: boolean;
}) {
  const view = result.view;
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");
  const seen = useRef(delivered); // a run already delivered when the page opened is not announced again
  const announce = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const dialog = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (delivered && !seen.current) announce.current = true;
    seen.current = delivered;
  }, [delivered]);
  useEffect(() => {
    // The panel opens once the result is in hand; a result that cannot be read is not announced by a popup (the
    // Result tab says so and offers Try again).
    if (announce.current && (view.status === "text" || view.status === "file")) {
      announce.current = false;
      setOpen(true);
    } else if (view.status === "error") announce.current = false;
  }, [view.status]);
  useEffect(() => {
    if (open) focusablesIn(dialog.current)[0]?.focus();
  }, [open]);

  const blob = view.status === "text" || view.status === "file" ? view.blob : null;
  const head = view.status === "text" ? resultHeadline(view.text, worldName) : null;
  const close = (): void => {
    setOpen(false);
    opener.current?.focus();
  };
  const copy = (): void => {
    if (view.status !== "text") return;
    try {
      Promise.resolve(navigator.clipboard.writeText(view.text))
        .then(() => setCopied("done"))
        .catch(() => setCopied("failed"));
    } catch {
      setCopied("failed"); // no clipboard here: the panel says so
    }
  };

  return (
    <section className="park-world-dock" aria-label="Delivery Dock" data-testid="delivery-dock">
      <div className="park-world-dockhead">
        <span className="park-world-docktitle">Delivery Dock</span>
        {delivered ? (
          <span className="park-world-dockstate">Result ready</span>
        ) : (
          <span className="park-world-dockstate">
            {failed ? "Nothing was delivered" : "Nothing delivered yet"}
          </span>
        )}
      </div>
      {delivered ? (
        <div className="park-world-dockbody">
          <p className="park-world-docksummary">
            {head ? <strong>{head.title}</strong> : <strong>{worldName}</strong>}
            {head?.summary ? ` — ${head.summary}` : ""}
          </p>
          <div className="park-world-resultactions">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                opener.current = document.activeElement as HTMLElement | null;
                setOpen(true);
              }}
              aria-haspopup="dialog"
            >
              Read the result
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={blob === null}
              onClick={() => blob && openResult(blob)}
            >
              Open result
            </Button>
          </div>
        </div>
      ) : null}
      {open ? (
        // biome-ignore lint/a11y/useKeyWithClickEvents: Escape closes the dialog (its onKeyDown); the backdrop click is the pointer shortcut
        <div
          className="park-world-slackbackdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) close();
          }}
        >
          <div
            ref={dialog}
            // biome-ignore lint/a11y/useSemanticElements: custom modal dialog with focus trap and role="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Result"
            className="park-world-slackdialog park-world-resultdialog"
            onKeyDown={(e: KeyboardEvent<HTMLElement>) =>
              handleSlackDialogKeyDown(e, dialog.current, close)
            }
          >
            <div className="park-world-slackhead">
              <div className="park-world-slacktitle">{head?.title ?? worldName}</div>
              {head?.summary ? <div className="park-world-slacksub">{head.summary}</div> : null}
            </div>
            <Body view={view} />
            <div className="park-world-resultactions">
              <Button
                variant="secondary"
                size="sm"
                disabled={blob === null}
                onClick={() => blob && openResult(blob)}
              >
                Open result
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={view.status !== "text"}
                onClick={copy}
              >
                Copy
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={blob === null}
                onClick={() => blob && saveResult(blob, worldId)}
              >
                Download
              </Button>
              <Button variant="secondary" size="sm" onClick={close}>
                Close
              </Button>
            </div>
            <output className="park-world-slackcount">
              {copied === "done"
                ? "Copied to the clipboard"
                : copied === "failed"
                  ? "Could not copy"
                  : ""}
            </output>
          </div>
        </div>
      ) : null}
    </section>
  );
}
