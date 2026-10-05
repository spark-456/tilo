// S-26 Meetings (PRD addendum FR-PA-03, FR-MTG-03/04; ADR-0016): the person's own meetings and the
// minutes of the one picked, every item with its evidence quotes and whether code verified it, and
// the one primary action: confirm the minutes. Fixture data only (src/people/data.ts), with a
// notice that says so. Meetings are owner-only (PE-05): there is no link, no transcript text and
// no activity figure of any kind (no talk time, no score), because the contracts hold none.
import type { Meeting, Minutes } from "@tilo/contracts";
import { type ReactNode, useState } from "react";
import { MEETINGS, MINUTES, PREVIEW_NOW, personName } from "../people/data";
import { Evidence, PreviewNote } from "../people/parts";
import { AppLink } from "./AppLink";
import { Chip, Page, Row, Section, longDate, stamp } from "./kit";
import type { ScreenProps } from "./routes";

const COVERAGE = { covered: "Covered", partial: "Partly covered", not_discussed: "Not discussed" };
const when = (m: Meeting): string => m.scheduled?.start ?? m.created_at;
const newest = [...MEETINGS].sort((a, b) => when(b).localeCompare(when(a)));

/** The chip of a meeting: its state in words (the colour never carries it alone). */
const stateOf = (m: Meeting, confirmed: boolean): readonly [string, string] =>
  m.status === "minuted"
    ? confirmed
      ? ["done", "Minutes confirmed"]
      : ["needs", "Minutes to confirm"]
    : m.status === "live"
      ? ["fyi", "Live"]
      : m.status === "discarded" || m.status === "deleted"
        ? ["soon", m.status === "discarded" ? "Discarded, nothing kept" : "Deleted"]
        : ["soon", m.status[0]?.toUpperCase() + m.status.slice(1)];

const Verified = ({ state }: { state: "verified" | "unverified" }) =>
  state === "verified" ? <Chip tone="done">Verified</Chip> : <Chip tone="needs">Unverified</Chip>;

export function S_26({ params }: ScreenProps) {
  const [confirmedAt, setConfirmedAt] = useState<Readonly<Record<string, string>>>({});
  const confirmedOf = (m: Meeting): string | null =>
    confirmedAt[m.id] ?? m.minutes_confirmed_by?.at ?? null;
  const picked =
    newest.find((m) => m.id === params[0]) ??
    newest.find((m) => m.status === "minuted" && m.minutes_confirmed_by === null) ??
    newest.find((m) => m.status === "minuted") ??
    newest[0];
  const minutes: Minutes | undefined = MINUTES.find((x) => x.meeting_id === picked?.id);
  const at = picked ? confirmedOf(picked) : null;

  return (
    <Page
      testid="meetings"
      title="Meetings"
      sub="Your meetings and their minutes. Every item points to what was said, and says whether Tilo checked it."
    >
      <PreviewNote what="This list" />
      <Section title="Your meetings">
        <ul className="blist" data-testid="meeting-list">
          {newest.map((m) => {
            const [tone, word] = stateOf(m, confirmedOf(m) !== null);
            return (
              <li key={m.id} className="bitem">
                <AppLink
                  to={`/meetings/${m.id}`}
                  className="meeting-pick"
                  {...(m.id === picked?.id ? { "aria-current": "page" as const } : {})}
                >
                  <b>{m.title}</b>
                  <span className="bitem-sub">
                    {longDate(when(m))}. {m.source === "bot" ? "Joined by Tilo" : "Uploaded"}.
                  </span>
                </AppLink>
                <Chip tone={tone}>{word}</Chip>
              </li>
            );
          })}
        </ul>
      </Section>
      {picked && (
        <Section
          title={`Minutes: ${picked.title}`}
          note={`Attendees: ${picked.attendees.map((a) => a.name).join(", ")}.`}
        >
          {minutes === undefined ? (
            <p className="empty-note" data-testid="no-minutes">
              {picked.status === "discarded" || picked.status === "deleted"
                ? "Nothing was kept from this meeting."
                : "There are no minutes yet. They appear here after the meeting is minuted."}
            </p>
          ) : (
            <MinutesView
              meeting={picked}
              minutes={minutes}
              confirmedAt={at}
              onConfirm={() => setConfirmedAt({ ...confirmedAt, [picked.id]: PREVIEW_NOW })}
            />
          )}
        </Section>
      )}
    </Page>
  );
}

function MinutesView({
  meeting: m,
  minutes: x,
  confirmedAt,
  onConfirm,
}: { meeting: Meeting; minutes: Minutes; confirmedAt: string | null; onConfirm: () => void }) {
  const item = (key: string, text: string, ids: readonly string[], chips: ReactNode) => (
    <Row key={key} name={text} state={chips}>
      <Evidence meeting={m.id} ids={ids} />
    </Row>
  );
  return (
    <div data-testid="minutes">
      <p className="section-note">
        Made {stamp(x.generated_at)}.
        {m.delete_minutes_after && ` Kept until ${longDate(m.delete_minutes_after)}.`}
      </p>
      {x.flagged && (
        <p className="people-flag" data-testid="minutes-flagged">
          The safety check flagged this transcript. Any draft made from these minutes needs your
          approval.
        </p>
      )}
      <div className="minutes-bar">
        {confirmedAt ? (
          <Chip tone="done">Confirmed by you, {longDate(confirmedAt)}</Chip>
        ) : (
          <>
            <button type="button" className="primary" onClick={onConfirm}>
              Confirm minutes
            </button>
            <p>Action items with no owner are not given to anyone.</p>
          </>
        )}
      </div>
      <h3 className="people-h3">Summary</h3>
      <ul className="blist people-list">
        {x.summary.map((s) => item(s.text, s.text, s.evidence, null))}
      </ul>
      <h3 className="people-h3">Decisions</h3>
      <ul className="blist people-list">
        {x.decisions.map((d) => item(d.text, d.text, d.evidence, <Verified state={d.state} />))}
      </ul>
      <h3 className="people-h3">Action items</h3>
      <ul className="blist people-list" data-testid="action-items">
        {x.action_items.map((a) =>
          item(
            a.id,
            a.text,
            a.evidence,
            <>
              <Chip tone={a.owner ? "fyi" : "soon"}>
                {a.owner
                  ? personName(a.owner)
                  : `No owner${a.owner_text ? ` (said ${a.owner_text})` : ""}`}
              </Chip>
              <Chip tone="fyi">
                {a.due ? longDate(`${a.due}T00:00:00Z`) : (a.due_text ?? "No due date")}
              </Chip>
              <Verified state={a.state} />
            </>,
          ),
        )}
      </ul>
      <h3 className="people-h3">Agenda</h3>
      <ul className="blist people-list">
        {x.agenda.map((g) =>
          item(g.title, g.title, g.evidence, <Chip tone="fyi">{COVERAGE[g.coverage]}</Chip>),
        )}
      </ul>
    </div>
  );
}
