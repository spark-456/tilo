// WORLDS-MANAGE: the row under the filters that arranges and clears the list. "Sort" orders the worlds (status, newest,
// oldest, name); "Select" turns the cards into checkboxes, and then the row says how many are picked and offers
// "Select all shown", "Delete selected" and "Done". Nothing is deleted from here without the confirm dialog.
import type { ChangeEvent } from "react";
import { Button } from "../../components";
import { SORTS, type SortKey } from "./arrange";

export function ManageBar({
  sort,
  onSort,
  canSelect,
  selecting,
  picked,
  shown,
  onSelecting,
  onSelectAll,
  onDelete,
}: {
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  /** False when no world in the list may be deleted (samples and teammates' worlds only). */
  canSelect: boolean;
  selecting: boolean;
  picked: number;
  shown: number;
  onSelecting: (on: boolean) => void;
  onSelectAll: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="park-worlds-manage">
      <label className="park-worlds-sort">
        <span className="park-worlds-sort__label">Sort</span>
        <select
          className="park-worlds-sort__select"
          value={sort}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => onSort(e.target.value as SortKey)}
        >
          {SORTS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {selecting ? (
        <div className="park-worlds-manage__picking" aria-live="polite">
          <span className="park-worlds-manage__count">
            {picked === 0 ? "Pick worlds to delete" : `${picked} selected`}
          </span>
          {shown > 0 ? (
            <Button variant="secondary" size="sm" onClick={onSelectAll}>
              Select all shown
            </Button>
          ) : null}
          <Button
            variant="primary"
            size="sm"
            onClick={onDelete}
            disabled={picked === 0}
            {...(picked === 0 ? { title: "Pick at least one world first" } : {})}
          >
            Delete selected
          </Button>
          <Button variant="secondary" size="sm" onClick={() => onSelecting(false)}>
            Done
          </Button>
        </div>
      ) : canSelect ? (
        <Button variant="secondary" size="sm" onClick={() => onSelecting(true)}>
          Select
        </Button>
      ) : null}
    </div>
  );
}
