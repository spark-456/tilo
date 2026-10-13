// The title row of the Worlds page: heading, total, subtitle, search, Share to Slack (FR-UX-17) and New world.
import type { ChangeEvent } from "react";
import type { SlackConnectorState } from "../../app/slackShare";
import type { Art } from "./art";

interface HeaderProps {
  art: Art;
  /** Every world, whatever the filters; null until the first load. */
  total: number | null;
  query: string;
  onQuery: (value: string) => void;
  onNew: () => void;
  slack?: SlackConnectorState | undefined;
  onShareSlack?: ((trigger: HTMLButtonElement) => void) | undefined;
}

const NO_SLACK_ID = "park-worlds-noslack";

export function Header({ art, total, query, onQuery, onNew, slack, onShareSlack }: HeaderProps) {
  return (
    <div className="park-worlds-header">
      <div className="park-worlds-header__titles">
        <div className="park-worlds-header__line">
          <h1 className="park-worlds-h1">Worlds</h1>
          {total === null ? null : <span className="park-worlds-total">{`${total} worlds`}</span>}
        </div>
        <p className="park-worlds-subtitle">
          Every job Tilo is running, sized by scale: cities, towns and villages.
        </p>
      </div>
      <div className="park-worlds-header__actions">
        <div className="park-worlds-search">
          {art.icon("search", 16)}
          <input
            className="park-worlds-search__input"
            aria-label="Search worlds"
            placeholder="Search worlds"
            value={query}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onQuery(e.target.value)}
          />
        </div>
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
