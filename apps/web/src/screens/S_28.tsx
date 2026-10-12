// S-28 Pinboards (PRD addendum FR-PB-01 to -08; ADR-0016): the team's pinboard as a table beside
// the person's own, side by side on a wide screen and in two tabs on a phone. Fixture data only
// (src/people/data.ts) and a notice that says so. Who sees what is code (src/people/pins.ts): a
// teammate's personal pin and proposal are never read, a removed entry is gone, and of another
// person only the display name shows (PE-20). "Get in touch" only drafts: sending is T3. No design
// export covers it, so it follows the pills of "Tilo Worlds" and the people rows of "Tilo Team".
import type { PinboardItem } from "@tilo/contracts";
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { LivePins } from "../people/LivePins";
import { MENTIONS, PINS, displayName } from "../people/data";
import { PersonTag, PreviewNote, SoonButton, pillLabel, shortDate } from "../people/parts";
import {
  KIND_WORD,
  type Kind,
  type Sort,
  type SortKey,
  canEdit,
  draftFor,
  personalBoard,
  sortPins,
  sourceLabel,
  taggedOn,
  teamBoard,
} from "../people/pins";
import { Chip, EmptyState, Page, Section, plural } from "./kit";

const KINDS: ReadonlyArray<readonly [Kind | "all", string]> = [
  ["all", "All"],
  ["note", "Notes"],
  ["decision", "Decisions"],
  ["deadline", "Deadlines"],
  ["link", "Links"],
];

const team = teamBoard(PINS);
const personal = personalBoard(PINS);

function Entry({ pin, action, setUp }: { pin: PinboardItem; action?: ReactNode; setUp?: boolean }) {
  const tagged = taggedOn(pin, MENTIONS);
  return (
    <th scope="row" data-label="Entry">
      <span className="pb-head">
        <b>{pin.title}</b>
      </span>
      <span className="pb-kinds">
        <Chip tone="fyi">{KIND_WORD[pin.kind]}</Chip>
        {pin.status === "proposed" && <Chip tone="soon">Proposed, only you see it</Chip>}
        {pin.flagged && <Chip tone="needs">Flagged: any follow-up needs you</Chip>}
        {action}
      </span>
      <span className="bitem-sub">{sourceLabel(pin)}.</span>
      {pin.url && <span className="bitem-sub pb-url">{pin.url.replace("https://", "")}</span>}
      {tagged.length > 0 && (
        <span className="bitem-sub pb-tags">
          Tagged:{" "}
          {tagged.map((u) => (
            <PersonTag key={u} user={u} />
          ))}
        </span>
      )}
      {setUp && (
        <span className="bitem-sub pb-setup">
          Set up by <PersonTag user={pin.set_up_by} />
        </span>
      )}
    </th>
  );
}

export function S_28() {
  const live = useClient() instanceof HttpClient;
  const [board, setBoard] = useState<"team" | "personal">("team");
  const [kind, setKind] = useState<Kind | "all">("all");
  const [sort, setSort] = useState<Sort>({ key: "updated", dir: -1 });
  const [draft, setDraft] = useState<PinboardItem | null>(null);
  const panel = useRef<HTMLElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (draft) panel.current?.focus();
  }, [draft]);
  if (live) return <LivePins />;
  // Closing hands focus back to the button that opened the draft (if its row is still listed).
  const closeDraft = () => {
    setDraft(null);
    if (opener.current?.isConnected) opener.current.focus();
  };

  const shown = (pins: PinboardItem[]) =>
    sortPins(
      pins.filter((p) => kind === "all" || p.kind === kind),
      sort,
    );
  const count = (k: Kind | "all") =>
    [...team, ...personal].filter((p) => k === "all" || p.kind === k).length;
  const rows = shown(team);
  const owned = rows.filter((p) => p.owner !== null);
  const unowned = rows.filter((p) => p.owner === null);
  const mine = shown(personal);

  const head = (k: SortKey, label: string, cls?: string) => (
    <th
      scope="col"
      className={cls}
      aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
    >
      <button
        type="button"
        className="pb-sort"
        onClick={() => setSort({ key: k, dir: sort.key === k && sort.dir === 1 ? -1 : 1 })}
      >
        <span className="pb-label">{label}</span>
        <span className="pb-arrow" data-dir={sort.key === k ? sort.dir : 0} aria-hidden="true" />
      </button>
    </th>
  );

  const teamRow = (p: PinboardItem) => (
    <Fragment key={p.id}>
      <tr data-testid="pin-row">
        <Entry
          pin={p}
          setUp
          action={
            canEdit(p) ? (
              <SoonButton text="Edit" name={`Edit: ${p.title}`} />
            ) : (
              <button
                type="button"
                className="secondary pb-act"
                aria-label={`Get in touch with ${displayName(p.set_up_by)} about ${p.title}`}
                onClick={(e) => {
                  opener.current = e.currentTarget;
                  setDraft(p);
                }}
              >
                Get in touch
              </button>
            )
          }
        />
        <td data-label="Responsible" className="pb-resp">
          {p.owner ? (
            <PersonTag user={p.owner} />
          ) : (
            <>
              <span aria-hidden="true">&ndash;</span>
              <span className="visually-hidden">Nobody yet</span>
            </>
          )}
        </td>
        <td data-label="Due" className="pb-date">
          {p.due ? shortDate(p.due) : "No date"}
        </td>
        <td data-label="Updated" className="pb-date">
          {shortDate(p.updated_at)}
        </td>
      </tr>
      {draft?.id === p.id && (
        <tr className="pb-draft-row">
          <td colSpan={4}>
            <section
              ref={panel}
              tabIndex={-1}
              className="pb-draft"
              aria-label="Draft message"
              data-testid="pin-draft"
              onKeyDown={(e) => {
                if (e.key === "Escape") closeDraft();
              }}
            >
              <h3 className="people-h3">Draft to {displayName(draft.set_up_by)}</h3>
              <label className="field">
                <span>Message</span>
                <textarea key={draft.id} rows={3} defaultValue={draftFor(draft)} />
              </label>
              <p className="section-note">
                Nothing is sent from this preview. A message to another person goes only after you
                approve it.
              </p>
              <div className="pb-actions">
                <SoonButton text="Send for approval" name="Send for approval" />
                <button type="button" className="secondary" onClick={closeDraft}>
                  Close draft
                </button>
              </div>
            </section>
          </td>
        </tr>
      )}
    </Fragment>
  );

  return (
    <Page
      testid="pinboards"
      title="Pinboards"
      sub="What your team has pinned, with who is responsible, and a board of your own that nobody else sees."
    >
      <PreviewNote what="This pinboard" />
      <fieldset className="filter-chips status-tabs people-strip" data-testid="pin-kinds">
        <legend className="visually-hidden">Filter entries by kind</legend>
        {KINDS.map(([k, word]) => (
          <label key={k} className="filter-chip">
            <input
              type="radio"
              name="pin-kind"
              value={k}
              checked={kind === k}
              onChange={() => setKind(k)}
            />
            <span>{pillLabel(word, count(k))}</span>
          </label>
        ))}
      </fieldset>
      <fieldset className="filter-chips status-tabs people-strip pb-tabs" data-testid="pin-tabs">
        <legend className="visually-hidden">Board</legend>
        {(
          [
            ["team", "Team board"],
            ["personal", "Your board"],
          ] as const
        ).map(([b, word]) => (
          <label key={b} className="filter-chip">
            <input
              type="radio"
              name="pin-board"
              value={b}
              checked={board === b}
              onChange={() => setBoard(b)}
            />
            <span>{word}</span>
          </label>
        ))}
      </fieldset>
      <div className="pb-room">
        <div className="pb-boards">
          <div className="pb-board" data-shown={board === "team"} data-testid="team-board">
            <Section title="Team board" note={plural(rows.length, "entry", "entries")}>
              {rows.length === 0 ? (
                <EmptyState
                  testid="team-empty"
                  compact
                  title="Nothing pinned for the team"
                  line={
                    kind === "all"
                      ? "Entries your team pins show up here."
                      : "No entries of this kind. Choose All to see the rest."
                  }
                />
              ) : (
                <table className="pb-table" data-testid="team-pins">
                  <caption className="visually-hidden">Team pinboard</caption>
                  <thead>
                    <tr>
                      {head("entry", "Entry")}
                      <th scope="col" className="pb-resp pb-plain">
                        <span className="pb-label">Responsible</span>
                      </th>
                      {head("due", "Due", "pb-date")}
                      {head("updated", "Updated", "pb-date")}
                    </tr>
                  </thead>
                  <tbody>{owned.map(teamRow)}</tbody>
                  {unowned.length > 0 && (
                    <tbody data-testid="pins-unowned">
                      <tr className="pb-lane">
                        <th scope="rowgroup" colSpan={4}>
                          <span className="pb-lane-title">Unowned</span>
                          <span className="pb-lane-note">Nobody is responsible yet.</span>
                        </th>
                      </tr>
                      {unowned.map(teamRow)}
                    </tbody>
                  )}
                </table>
              )}
            </Section>
          </div>
          <div className="pb-board" data-shown={board === "personal"} data-testid="personal-board">
            <Section
              title="Your board"
              note={`Only you see this. ${plural(mine.length, "entry", "entries")}`}
            >
              {mine.length === 0 ? (
                <EmptyState
                  testid="personal-empty"
                  compact
                  title="Nothing on your board"
                  line="Notes you keep for yourself, and what Tilo adds for you, show up here."
                />
              ) : (
                <table className="pb-table" data-testid="personal-pins">
                  <caption className="visually-hidden">Your pinboard</caption>
                  <thead>
                    <tr>
                      {head("entry", "Entry")}
                      {head("due", "Due", "pb-date")}
                      {head("updated", "Updated", "pb-date")}
                    </tr>
                  </thead>
                  <tbody>
                    {mine.map((p) => (
                      <tr key={p.id} data-testid="pin-row">
                        <Entry
                          pin={p}
                          action={
                            canEdit(p) && <SoonButton text="Edit" name={`Edit: ${p.title}`} />
                          }
                        />
                        <td data-label="Due" className="pb-date">
                          {p.due ? shortDate(p.due) : "No date"}
                        </td>
                        <td data-label="Updated" className="pb-date">
                          {shortDate(p.updated_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          </div>
        </div>
      </div>
    </Page>
  );
}
