// S-28 Pinboards (PRD addendum FR-PB-01 to -08; ADR-0016): the team's pinboard as a table beside
// the person's own, side by side on a wide screen and in two tabs on a phone. Fixture data only
// (src/people/data.ts) and a notice that says so. Who sees what is code (src/people/pins.ts): a
// teammate's personal pin and proposal are never read, a removed entry is gone, and of another
// person only the display name shows (PE-20). "Get in touch" only drafts: sending is T3. No design
// export covers it, so it follows the pills of "Tilo Worlds" and the people rows of "Tilo Team".
import type { PinboardItem } from "@tilo/contracts";
import { type ReactNode, useEffect, useRef, useState } from "react";
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

function Entry({ pin, children }: { pin: PinboardItem; children?: ReactNode }) {
  const tagged = taggedOn(pin, MENTIONS);
  return (
    <th scope="row" data-label="Entry">
      <span className="prow-title">
        <b>{pin.title}</b>
        <span className="prow-chips">
          <Chip tone="fyi">{KIND_WORD[pin.kind]}</Chip>
          {pin.status === "proposed" && <Chip tone="soon">Proposed, only you see it</Chip>}
          {pin.flagged && <Chip tone="needs">Flagged: any follow-up needs you</Chip>}
        </span>
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
      {children}
    </th>
  );
}

export function S_28() {
  const [board, setBoard] = useState<"team" | "personal">("team");
  const [kind, setKind] = useState<Kind | "all">("all");
  const [sort, setSort] = useState<Sort>({ key: "updated", dir: -1 });
  const [draft, setDraft] = useState<PinboardItem | null>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (draft) panel.current?.focus();
  }, [draft]);

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

  const head = (k: SortKey, label: string) => (
    <th
      scope="col"
      aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
    >
      <button
        type="button"
        className="pb-sort"
        onClick={() => setSort({ key: k, dir: sort.key === k && sort.dir === 1 ? -1 : 1 })}
      >
        {label}
        <span className="pb-arrow" data-dir={sort.key === k ? sort.dir : 0} aria-hidden="true" />
      </button>
    </th>
  );

  const teamRow = (p: PinboardItem) => (
    <tr key={p.id} data-testid="pin-row">
      <Entry pin={p} />
      <td data-label="Responsible">
        {p.owner ? <PersonTag user={p.owner} /> : <Chip tone="soon">Unowned</Chip>}
      </td>
      <td data-label="Set up by">
        <PersonTag user={p.set_up_by} />
        {canEdit(p) ? (
          <SoonButton text="Edit" name={`Edit: ${p.title}`} />
        ) : (
          <button
            type="button"
            className="secondary"
            aria-label={`Get in touch with ${displayName(p.set_up_by)} about ${p.title}`}
            onClick={() => setDraft(p)}
          >
            Get in touch
          </button>
        )}
      </td>
      <td data-label="Due">{p.due ? shortDate(p.due) : "No date"}</td>
      <td data-label="Updated">{shortDate(p.updated_at)}</td>
    </tr>
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
                    <th scope="col" className="pb-plain">
                      Responsible
                    </th>
                    <th scope="col" className="pb-plain">
                      Set up by
                    </th>
                    {head("due", "Due")}
                    {head("updated", "Updated")}
                  </tr>
                </thead>
                <tbody>{owned.map(teamRow)}</tbody>
                {unowned.length > 0 && (
                  <tbody data-testid="pins-unowned">
                    <tr className="pb-lane">
                      <th scope="rowgroup" colSpan={5}>
                        Unowned <span>Nobody is responsible yet.</span>
                      </th>
                    </tr>
                    {unowned.map(teamRow)}
                  </tbody>
                )}
              </table>
            )}
            {draft && (
              <section
                ref={panel}
                tabIndex={-1}
                className="pb-draft"
                aria-label="Draft message"
                data-testid="pin-draft"
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
                  <button type="button" className="secondary" onClick={() => setDraft(null)}>
                    Close draft
                  </button>
                </div>
              </section>
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
                    {head("due", "Due")}
                    {head("updated", "Updated")}
                  </tr>
                </thead>
                <tbody>
                  {mine.map((p) => (
                    <tr key={p.id} data-testid="pin-row">
                      <Entry pin={p}>
                        {canEdit(p) && <SoonButton text="Edit" name={`Edit: ${p.title}`} />}
                      </Entry>
                      <td data-label="Due">{p.due ? shortDate(p.due) : "No date"}</td>
                      <td data-label="Updated">{shortDate(p.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </div>
      </div>
    </Page>
  );
}
