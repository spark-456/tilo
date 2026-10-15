// The title row of the Worlds page (STUDIO-3, "Tilo S Worlds.dc.html"): heading, total, subtitle, Share to Slack
// (FR-UX-17) and New world, the page's one filled button.
import type { SlackConnectorState } from "../../app/slackShare";
import type { Art } from "./art";

interface HeaderProps {
  art: Art;
  /** Every world, whatever the filters; null until the first load. */
  total: number | null;
  onNew: () => void;
  slack?: SlackConnectorState | undefined;
  onShareSlack?: ((trigger: HTMLButtonElement) => void) | undefined;
}

const NO_SLACK_ID = "park-worlds-noslack";

export function Header({ art, total, onNew, slack, onShareSlack }: HeaderProps) {
  return (
    <div className="park-worlds-header">
      <div className="park-worlds-header__titles">
        <div className="park-worlds-header__line">
          <h1 className="park-worlds-h1">Worlds</h1>
          {total === null ? null : (
            <span className="park-worlds-total">{`${total} ${total === 1 ? "world" : "worlds"}`}</span>
          )}
        </div>
        <p className="park-worlds-subtitle">
          Every bigger job gets its own little city. Here are all of yours.
        </p>
      </div>
      <div className="park-worlds-header__actions">
        {slack && onShareSlack ? (
          <>
            <button
              type="button"
              className="park-worlds-slack"
              disabled={!slack.connected}
              aria-disabled={!slack.connected ? "true" : undefined}
              aria-describedby={!slack.connected ? NO_SLACK_ID : undefined}
              title={!slack.connected ? slack.disabledReason : "Share a world link to Slack"}
              onClick={(e) => onShareSlack(e.currentTarget)}
            >
              {art.icon("share", 15)}
              Share to Slack
            </button>
            {!slack.connected ? (
              <span id={NO_SLACK_ID} className="park-worlds-sr">
                {slack.disabledReason}
              </span>
            ) : null}
          </>
        ) : null}
        <button type="button" className="park-worlds-new" onClick={onNew}>
          {art.icon("plus", 15)}
          New world
        </button>
      </div>
    </div>
  );
}
