// The title row of the Worlds page: heading, total, subtitle, search and New world.
import type { ChangeEvent } from "react";
import type { Art } from "./art";

interface HeaderProps {
  art: Art;
  /** Every world, whatever the filters; null until the first load. */
  total: number | null;
  query: string;
  onQuery: (value: string) => void;
  onNew: () => void;
}

export function Header({ art, total, query, onQuery, onNew }: HeaderProps) {
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
        <button type="button" className="park-worlds-new" onClick={onNew}>
          {art.icon("plus", 15)}
          New world
        </button>
      </div>
    </div>
  );
}
