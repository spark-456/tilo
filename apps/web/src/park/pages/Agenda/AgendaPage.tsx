// The Agenda page (WEB-9): pins from the team and Tilo, and a week that stays in sync. Pixel port of
// design_handoff_tilo_web_app/design/Tilo App Agenda.dc.html (user's prototype, ADR-0003a).
// Data comes only from the Park Api (fixture or live, with its `source`); the page reads approvals from
// `app.dec` (the shell's `decide(key)` is the only way one changes); navigation only through `app.go`.
// No motion until WEB-3 (BQ-WEB-3).
import { type ReactNode, useMemo, useRef, useState } from "react";
import { API_URL, appCheckToken, authToken, sessionView } from "../../../api/ClientProvider";
import type { HostState } from "../../../api/connect";
import { liveConnectFlow } from "../../../api/connectEnv";
import { HttpClient } from "../../../api/http";
import { EmptyState, ErrorState, LoadingState } from "../../../design/tilo-t";
import type { Api } from "../../api/index";
import { isCalendarEntry } from "../../api/live/agendaFromPlate";
import { meetingHostApi } from "../../api/live/meetingHost";
import { meetingMinutesApi } from "../../api/live/meetingMinutes";
import type { PeopleRow } from "../../api/live/peopleLists";
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import type { Agenda, AgendaPlateRow, Decision, LiveAgenda } from "../../api/types";
import { useParkApi } from "../../app/context";
import { useStagedCount } from "../../app/useStaged";
import { Button, PageSheet } from "../../components";
import { FirstRunPanels } from "../../sample/FirstRunPanels";
import { useFirstRunPreview } from "../../sample/useFirstRunPreview";
import { AppLink } from "../../shared/AppLink";
import "../../components/park.components.css";
import type { AppCtx } from "../../app/AppCtx";
import { type HostForm, refusedBeforeSend } from "../../shared/hostMeetingRules";
import { AgendaNewMenu } from "./AgendaNewMenu";
import { Boards } from "./Boards";
import { LiveWeek } from "./LiveWeek";
import { PeopleLists } from "./PeopleLists";
import { ScheduleWithOthersDialog } from "./ScheduleWithOthersDialog";
import { Week } from "./Week";
import { icon } from "./icons";
import { BOARDS, boardLimits } from "./model";
import { useAgenda, useAgendaUi } from "./useAgenda";
import "./Agenda.css";
import "./Agenda.studio.css";

export interface AgendaPageProps {
  app: AppCtx;
}

function Frame({ source, children }: { source?: string; children?: ReactNode }) {
  return (
    <div
      className="park-agenda-root"
      data-testid="park-page-agenda"
      data-park-agenda=""
      data-source={source}
    >
      <PageSheet gap={30}>{children}</PageSheet>
    </div>
  );
}

/** HR-1: no calendar sync event stands behind the sample week, so the chip says so instead of "synced just now". */
const SAMPLE_SYNC = "Sample data · no calendar sync recorded";

function humanAgendaDate(value: string): string {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(date.getTime())) return "Date not supplied";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const day = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
  return sameDay
    ? `Today ${new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date)}`
    : `${day}${/^\d{4}-\d{2}-\d{2}$/.test(value) ? "" : ` · ${new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date)}`}`;
}

function Ready({
  A,
  decisions,
  app,
  api,
  sample,
}: { A: Agenda; decisions: Decision[]; app: AppCtx; api: Api; sample: boolean }) {
  const ui = useAgendaUi(A, decisions, app, api);
  // The boards draw one after the other, a pin per task, then the week: top to bottom, and a board that has not
  // started holds its cell in the grid, so nothing already drawn moves (WEB-MOTION-2, FR-UX-12: no long task while
  // pages change).
  const counts = BOARDS.map((b) => ui.pins.filter((p) => p.board === b.key).length);
  // The steps are those of the pins that came with the page: a pin the person adds later shows at once and does not
  // take the week away for a task.
  const steps = useRef(counts.reduce((a, n) => a + n, 0) + 2).current;
  const count = useStagedCount(steps);
  const done = count >= steps;
  return (
    <>
      <div className="park-agenda-head">
        <div className="park-agenda-titles">
          <h1 className="park-agenda-title">Agenda</h1>
          <p className="park-agenda-lede">
            {`${A.rules ? `${A.rules.dateLine}. ` : ""}Pins from your team and Tilo, and your week.`}
          </p>
          {sample ? (
            <p>Sample week: no meetings are booked, invitations sent or reminders scheduled.</p>
          ) : null}
        </div>
        <div className="park-agenda-actions">
          <div className="park-agenda-synced" data-testid="agenda-synced">
            {sample ? SAMPLE_SYNC : "No calendar sync recorded"}
          </div>
          <Button variant="primary" icon={icon("calendar", 16)} onClick={ui.findTime}>
            Find a time
          </Button>
        </div>
      </div>
      <Boards
        A={A}
        ui={ui}
        app={app}
        limits={boardLimits(counts, done ? Number.POSITIVE_INFINITY : count - 1)}
      />
      {done ? <Week A={A} ui={ui} app={app} /> : null}
    </>
  );
}

export function AgendaPage({ app }: AgendaPageProps) {
  const preview = useFirstRunPreview();
  // JUDGE-FIRST-RUN F1: a judge is a member of the org, so the real Agenda shows; a first visit adds the labelled
  // recorded examples below it instead of hiding it.
  return (
    <>
      <PersonalAgendaPage app={app} />
      {preview ? <FirstRunPanels page="agenda" app={app} embedded /> : null}
    </>
  );
}
function PersonalAgendaPage({ app }: AgendaPageProps) {
  const api = useParkApi();
  const state = useAgenda(api);

  if (state.status === "not-built" || state.status === "error") {
    return (
      <Frame>
        <h1 className="park-agenda-title">Agenda</h1>
        {state.status === "not-built" ? (
          <EmptyState
            title="Agenda data is unavailable"
            body="Pins and your week show here once the Agenda is connected."
          />
        ) : (
          <ErrorState title="The Agenda could not load" body="Try again in a moment." />
        )}
      </Frame>
    );
  }
  if (state.status === "loading")
    return (
      <Frame>
        <LoadingState layout="calendar" caption="Loading your Agenda" />
      </Frame>
    );
  return (
    <Frame source={state.source}>
      {state.data.days === null ? (
        <Plate A={state.data} />
      ) : (
        <Ready
          A={state.data}
          decisions={state.decisions}
          app={app}
          api={api}
          sample={state.source !== "live"}
        />
      )}
    </Frame>
  );
}

function Plate({ A }: { A: LiveAgenda }) {
  const [peopleKey, setPeopleKey] = useState(0);
  const [meetings, setMeetings] = useState<PeopleRow[]>([]);
  const [schedule, setSchedule] = useState<{ start: string; minutes: number } | null>(null);
  const demo = sessionView.demo();
  const http = useMemo(() => {
    const baseUrl = API_URL?.trim();
    return baseUrl && !demo ? new HttpClient({ baseUrl, appCheckToken, authToken }) : null;
  }, [demo]);
  const host = useMemo(() => (http ? meetingHostApi(http) : null), [http]);
  const hostFlow = useMemo(() => (http ? liveConnectFlow() : null), [http]);
  const hostState = useMemo<(() => Promise<HostState>) | undefined>(
    () => (hostFlow ? () => hostFlow.meetingHost() : undefined),
    [hostFlow],
  );
  const minutes = useMemo(() => (http ? meetingMinutesApi(http) : null), [http]);
  const getJson = useMemo(() => (http ? (path: string) => http.getJson(path) : null), [http]);
  const meetHere = async (start: string, minutes: number) => {
    if (!host) throw new Error("Meeting host is unavailable");
    const { you } = await host.people();
    const date = new Date(start);
    const local = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    const form: HostForm = { title: "Meet with Tilo", start: local, minutes, attested: true };
    const id = await host.create(form, crypto.randomUUID());
    try {
      await host.world(id);
      await host.start(id, [you]);
    } catch (error) {
      if (refusedBeforeSend(error)) await host.remove(id).catch(() => undefined);
      throw error;
    }
  };
  const createPin = http
    ? async (title: string, idempotencyKey: string) => {
        const answer = await http.postJson(
          "/v1/pinboards",
          { title },
          { "Idempotency-Key": idempotencyKey },
        );
        if (
          !answer ||
          typeof answer !== "object" ||
          !("id" in answer) ||
          typeof answer.id !== "string" ||
          !/^pb_[A-Za-z0-9_]{1,48}$/.test(answer.id)
        )
          throw new Error("Unreadable pin reply");
      }
    : null;
  if (A.setupRequired)
    return (
      <>
        <h1 className="park-agenda-title">Agenda</h1>
        <output>{ORGANISATION_SETUP}</output>
      </>
    );
  const list = (rows: AgendaPlateRow[], empty: string) =>
    rows.length ? (
      <ul>
        {rows.map((r) => (
          <li key={`${r.ref.kind}:${r.ref.id}`}>
            <strong>{r.title ?? "Untitled item"}</strong>
            {r.due ? (
              <p>
                Due <time dateTime={r.due}>{humanAgendaDate(r.due)}</time>
              </p>
            ) : null}
            {isCalendarEntry(r) && r.at ? (
              <p>
                <time dateTime={r.at}>{humanAgendaDate(r.at)}</time>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    ) : (
      <p>{empty}</p>
    );
  return (
    <>
      <div className="park-agenda-titles">
        <div className="park-agenda-t-head">
          <div>
            <h1 className="park-agenda-title">Agenda</h1>
            <p className="park-agenda-lede">
              Tilo prepares a brief before each meeting and takes notes in the ones you invite it
              to.
            </p>
          </div>
          <AgendaNewMenu
            createPin={createPin}
            canHost={http !== null}
            onPinCreated={() => setPeopleKey((n) => n + 1)}
            onSchedule={() => {
              const next = new Date(Date.now() + 5 * 60_000);
              next.setMinutes(Math.ceil(next.getMinutes() / 15) * 15, 0, 0);
              setSchedule({ start: next.toISOString(), minutes: 15 });
            }}
          />
        </div>
        <p className="park-agenda-date">
          {A.plate.today ? humanAgendaDate(A.plate.today) : "This week"}
        </p>
      </div>
      <LiveWeek
        rows={A.plate.rows}
        parked={A.plate.parked}
        meetings={meetings}
        onSchedule={(start, minutes) => setSchedule({ start, minutes })}
        host={host}
        {...(hostState ? { hostState } : {})}
        minutes={minutes}
        getJson={getJson}
        onMeetHere={meetHere}
        onDeleted={() => setPeopleKey((n) => n + 1)}
      />
      <div className="park-agenda-studio">
        <div className="park-agenda-studiomain">
          <section aria-label="Your plate" className="park-agenda-state">
            <h2>Your plate</h2>
            {list(
              A.plate.rows.filter((r) => !isCalendarEntry(r)),
              "Nothing on your plate",
            )}
            <AppLink to="/home">Morning brief on Home</AppLink>
            {A.plate.truncated ? <p>Showing a limited list.</p> : null}
          </section>
          <section aria-label="Parked work" className="park-agenda-state">
            <h2>Parked work</h2>
            {list(A.plate.parked, "No parked work.")}
          </section>
          <div id="agenda-meetings">
            <PeopleLists key={peopleKey} onMeetings={setMeetings} />
          </div>
        </div>
        <aside className="park-agenda-studioside">
          <section aria-label="Event details" className="park-agenda-state park-agenda-sidecard">
            <h2>Event details</h2>
            <p>Select a meeting to see its details and any prepared brief.</p>
          </section>
          <section aria-label="Available times" className="park-agenda-state park-agenda-sidecard">
            <h2>Tilo suggests</h2>
            <p>Suggested times will appear when Tilo has real availability to share.</p>
          </section>
          <section aria-label="Boards" className="park-agenda-state park-agenda-sidecard">
            <h2>Boards</h2>
            <p>Pinboards appear here when you have saved items.</p>
          </section>
        </aside>
      </div>
      {schedule ? (
        <ScheduleWithOthersDialog
          api={host}
          start={schedule.start}
          minutes={schedule.minutes}
          onClose={() => setSchedule(null)}
          onScheduled={() => setPeopleKey((n) => n + 1)}
        />
      ) : null}
    </>
  );
}

/** Keep the page structure visible while reads are empty; each line describes data the API can supply. */
