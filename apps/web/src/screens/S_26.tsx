// S-26 Meetings (PRD addendum FR-PA-03, FR-MTG-03/04; ADR-0016): the person's own meetings with a
// strip of filter pills and real counts, and the minutes of the one picked, every item with its
// evidence quotes and whether code verified it, and the one primary action: confirm the minutes.
// Fixture data only (src/people/data.ts), with a notice that says so. Meetings are owner-only
// (PE-05): there is no link, no transcript text and no activity figure of any kind (no talk time,
// no score), because the contracts hold none. No design export covers it, so it follows the
// pills of "Tilo Worlds" and the people rows of "Tilo Team" in neutral role tokens.
import type { Meeting, Minutes } from "@tilo/contracts";
import { type ReactNode, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { HostMeeting } from "../people/HostMeeting";
import { LiveLists } from "../people/LiveLists";
import { ALL_MEETINGS, MEETINGS, MINUTES, PREVIEW_NOW, SIGNED_IN } from "../people/data";
import { Evidence, PersonTag, PreviewNote, pillLabel } from "../people/parts";
import { AppLink } from "./AppLink";
import { Chip, Page, Section, longDate, stamp } from "./kit";
import type { ScreenProps } from "./routes";

const COVERAGE = { covered: "Covered", partial: "Partly covered", not_discussed: "Not discussed" };
const when = (m: Meeting): string => m.scheduled?.start ?? m.created_at;
const newest = [...MEETINGS].sort((a, b) => when(b).localeCompare(when(a)));

type Group = "all" | "needs" | "confirmed" | "other";
const GROUPS: ReadonlyArray<readonly [Group, string]> = [
  ["all", "All"],
  ["needs", "Needs confirming"],
  ["confirmed", "Confirmed"],
  ["other", "Other"],
];

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

/** One minutes row: the text with its chips on the title row, the evidence trigger on the line
 * under it. `plain` is regular weight (the summary); the rest are the items to read first. */
function Item({
  meeting,
  text,
  ids,
  chips,
  sub,
  plain,
}: {
  meeting: string;
  text: string;
  ids: readonly string[];
  chips?: ReactNode;
  sub?: ReactNode;
  plain?: boolean;
}) {
  return (
    <li className="mrow">
      <div className="mrow-title">
        <span className="mrow-text" data-plain={plain ? "true" : undefined}>
          {text}
        </span>
        {chips && <span className="prow-chips">{chips}</span>}
      </div>
      <div className="mrow-sub">
        {sub}
        <Evidence meeting={meeting} ids={ids} />
      </div>
    </li>
  );
}

export function S_26({ params }: ScreenProps) {
  const live = useClient() instanceof HttpClient;
  const [confirmedAt, setConfirmedAt] = useState<Readonly<Record<string, string>>>({});
  const [group, setGroup] = useState<Group>("all");
  if (live) return <LiveLists kind="meetings" />;
  const confirmedOf = (m: Meeting): string | null =>
    confirmedAt[m.id] ?? m.minutes_confirmed_by?.at ?? null;
  const groupOf = (m: Meeting): Group =>
    m.status !== "minuted" ? "other" : confirmedOf(m) === null ? "needs" : "confirmed";
  const count = (g: Group) => newest.filter((m) => g === "all" || groupOf(m) === g).length;
  const picked =
    newest.find((m) => m.id === params[0]) ??
    ALL_MEETINGS.find((m) => m.id === params[0]) ?? // an upcoming meeting is opened by address, not listed here
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
      <fieldset className="filter-chips status-tabs people-strip" data-testid="meeting-strip">
        <legend className="visually-hidden">Filter meetings</legend>
        {GROUPS.map(([g, word]) => (
          <label key={g} className="filter-chip">
            <input
              type="radio"
              name="meetings-group"
              value={g}
              checked={group === g}
              onChange={() => setGroup(g)}
            />
            <span>{pillLabel(word, count(g))}</span>
          </label>
        ))}
      </fieldset>
      <Section title="Your meetings">
        <ul className="blist" data-testid="meeting-list">
          {newest
            .filter((m) => group === "all" || groupOf(m) === group)
            .map((m) => {
              const [tone, word] = stateOf(m, confirmedOf(m) !== null);
              return (
                <li key={m.id} className="bitem meeting-row">
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
        <Section title={`Minutes: ${picked.title}`}>
          <ul className="people-tags" aria-label="Attendees">
            {picked.attendees.map((a) => (
              <li key={a.name}>
                <PersonTag name={a.name} plain={a.user === null} />
              </li>
            ))}
          </ul>
          <HostMeeting meeting={picked} me={SIGNED_IN} />
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
        {x.summary.map((s) => (
          <Item key={s.text} meeting={m.id} text={s.text} ids={s.evidence} plain />
        ))}
      </ul>
      <h3 className="people-h3">Decisions</h3>
      <ul className="blist people-list">
        {x.decisions.map((d) => (
          <Item
            key={d.text}
            meeting={m.id}
            text={d.text}
            ids={d.evidence}
            chips={<Verified state={d.state} />}
          />
        ))}
      </ul>
      <h3 className="people-h3">Action items</h3>
      <ul className="blist people-list" data-testid="action-items">
        {x.action_items.map((a) => (
          <Item
            key={a.id}
            meeting={m.id}
            text={a.text}
            ids={a.evidence}
            chips={
              <>
                <Chip tone={a.due ? "fyi" : "soon"}>
                  {a.due ? `Due ${longDate(`${a.due}T00:00:00Z`)}` : (a.due_text ?? "No due date")}
                </Chip>
                <Verified state={a.state} />
              </>
            }
            sub={
              a.owner ? (
                <PersonTag user={a.owner} />
              ) : (
                <span className="evidence-none">
                  No owner{a.owner_text ? ` (said ${a.owner_text})` : ""}.
                </span>
              )
            }
          />
        ))}
      </ul>
      <h3 className="people-h3">Agenda</h3>
      <ul className="blist people-list">
        {x.agenda.map((g) => (
          <Item
            key={g.title}
            meeting={m.id}
            text={g.title}
            ids={g.evidence}
            chips={<Chip tone="fyi">{COVERAGE[g.coverage]}</Chip>}
          />
        ))}
      </ul>
    </div>
  );
}
