// WEB-10: the Park "Team" page (design "Tilo App Team.dc.html", inventory.md "Team"; plan section 10).
// Data only through the park Api (useParkApi); navigation only through app.go; nothing here approves or
// starts work. Plan 8b (designed, no Api yet): invite, role change, remove, resend and cancel, the five rule
// switches and the backup picker are page state; the "Now / 2h ago" activity strings and the wait times are
// the fixture's own text. Motion (the details fade, the 1.8 s flash timer, hover fades) arrives with WEB-3b.
import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Team, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { isNotBuilt, useLiveTeam } from "../../app/useLiveTeam";
import { useStaged } from "../../app/useStaged";
import { Button, PageSheet } from "../../components";
import { FirstRunPanels } from "../../sample/FirstRunPanels";
import { useFirstRunPreview } from "../../sample/useFirstRunPreview";
import { ConsoleSection, MailSection } from "../../shared/RunAdmin";
import { Coverage } from "./Coverage";
import { LiveMembers } from "./LiveMembers";
import { LiveBody, LiveInvite, StatusLine } from "./LiveTeam";
import { Members } from "./Members";
import { MatrixCard, RulesCard } from "./Rules";
import { SelfServeTeams } from "./SelfServeTeams";
import { Helpers, WhoCanSayYes } from "./Studio";
import { TeamResources } from "./TeamResources";
import "./Team.css";
import "./Team.studio.css";
import { agentArt, icon } from "./teamKit";
import {
  type Backups,
  type CoverRow,
  type Loaded,
  MUST_ASK_RULES,
  type Member,
  type MyTeamName,
  canChangeRole,
  coverRows,
  isValidEmail,
  memberViews,
  peopleCount,
  reassignWorlds,
  withMyTeams,
} from "./teamModel";

function Top({ count, children }: { count?: string | undefined; children?: ReactNode }) {
  return (
    <div className="park-team-top">
      <div className="park-team-titles">
        <div className="park-team-titlerow">
          <h1 className="park-team-h1" tabIndex={-1}>
            Team
          </h1>
          {count ? <span className="park-team-count">{count}</span> : null}
        </div>
        <p className="park-team-intro">
          The people who share this space, and the helpers who work for all of you.
        </p>
      </div>
      {children}
    </div>
  );
}

/** The shell's page frame: the `park-page-<id>` marker WEB-3a's Placeholder carries, then the 22px sheet. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div data-testid="park-page-team">
      <PageSheet gap={22}>{children}</PageSheet>
    </div>
  );
}

export function TeamPage({ app }: { app: AppCtx }) {
  const preview = useFirstRunPreview();
  if (app.params.focus === "mail")
    return (
      <Frame>
        <Top />
        <h2>Email Autopilot</h2>
        <MailSection />
      </Frame>
    );
  if (app.params.focus === "console")
    return (
      <Frame>
        <Top />
        <h2>Team Lead console</h2>
        <ConsoleSection />
      </Frame>
    );
  // JUDGE-FIRST-RUN F1: a judge is a member of the org, so the real team shows; a first visit adds the labelled
  // fictional examples below it instead of hiding it.
  return (
    <>
      <PersonalTeamPage app={app} />
      {preview ? <FirstRunPanels page="team" app={app} embedded /> : null}
    </>
  );
}
function PersonalTeamPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const { dec, added, toast } = app;
  const [loaded, setLoaded] = useState<Loaded | "failed" | null>(null);
  const [controlsOnly, setControlsOnly] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [liveTeam, setLiveTeam] = useState<Team | null>(null);
  const [teamWorlds, setTeamWorlds] = useState<World[]>([]);
  const [teamWorldsState, setTeamWorldsState] = useState<"loading" | "ready" | "failed">("loading");
  const [people, setPeople] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [mine, setMine] = useState<{ you: string | null; teams: MyTeamName[] }>({
    you: null,
    teams: [],
  });
  const onMine = useCallback(
    (you: string | null, teams: MyTeamName[]) => setMine({ you, teams }),
    [],
  );
  const sent = useRef(0);
  useEffect(() => {
    let live = true;
    setLiveTeam(null);
    setLoaded(null);
    api
      .getTeam()
      .then(async (t) => {
        if (!live) return;
        if (t.source === "live") {
          setLiveTeam(t.data);
          const worlds = await api.getWorlds(dec, added).catch(() => null);
          if (live && worlds?.source === "live") {
            setTeamWorlds(worlds.data);
            setTeamWorldsState("ready");
          } else if (live) {
            setTeamWorldsState("failed");
          }
          return;
        }
        const [pol, l, s, w] = await Promise.all([
          api.getTeamPolicy(),
          api.getLearn(),
          api.getSkills(),
          api.getWorlds(dec, added),
        ]);
        if (!live) return;
        setPeople((ps) => ps ?? t.data.people);
        setLoaded({
          team: t.data,
          policy: pol.data,
          helpers: l.data.helpers,
          skills: s.data,
          worlds: w.data,
        });
      })
      .catch((e: unknown) => {
        if (!live) return;
        if (isNotBuilt(e)) setControlsOnly(true);
        else setLoaded("failed");
      });
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  const valid = isValidEmail(email);
  const invite = () => {
    const to = email.trim();
    if (!valid) return toast("Enter a work email to invite");
    sent.current += 1;
    const pending = { id: `i${sent.current}`, name: to, email: to, dept: "", role: "Member" };
    setPeople((ps) => [
      ...(ps ?? []),
      { ...pending, active: "Pending", c: "transparent", pending: true },
    ]);
    setEmail("");
    toast(`This is a sample team, so no invite was sent to ${to}.`);
  };

  // One stable root: the frame and the heading are the same elements while loading, loaded or failed, so
  // the h1 the shell focuses on arrival is not remounted when the data lands.
  if (controlsOnly) return <LiveControlsPage app={app} />;

  const ready =
    !liveTeam && loaded && loaded !== "failed" && people
      ? {
          data: loaded,
          people,
          // The invite placeholder takes the owner's mail domain from the team data.
          domain:
            loaded.team.people.find((p) => p.role === "Owner")?.email?.split("@")[1] ??
            "company.com",
        }
      : null;
  return (
    <Frame>
      <Top
        count={
          liveTeam
            ? liveTeam.setupRequired
              ? undefined
              : peopleCount(liveTeam.people.length)
            : ready
              ? peopleCount(ready.people.length)
              : undefined
        }
      >
        {ready ? (
          <div className="park-team-invite">
            <div className="park-team-field">
              {icon("mail", 16)}
              <input
                className="park-team-input"
                aria-label="Invite by email"
                placeholder={`name@${ready.domain}`}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && invite()}
              />
            </div>
            <Button
              variant="primary"
              disabled={!valid}
              title={
                valid
                  ? undefined
                  : `Enter a work email at ${ready?.domain ?? "your company"} to invite`
              }
              style={{ opacity: valid ? 1 : 0.6 }}
              onClick={invite}
            >
              Invite
            </Button>
          </div>
        ) : null}
      </Top>
      {liveTeam?.setupRequired ? (
        <LiveMembers team={liveTeam} />
      ) : liveTeam ? (
        <>
          {/* UI-STUDIO-5 (design "Tilo S Team"): your teams and the people on the left, who can say yes on the
              right, the helpers under them; the owner's settings open below, full width. */}
          <div className="park-team-studio">
            <div className="park-team-main">
              <SelfServeTeams onLoaded={onMine} />
              <LiveMembers team={withMyTeams(liveTeam, mine.you, mine.teams)} />
            </div>
            <WhoCanSayYes />
          </div>
          <TeamResources worlds={teamWorlds} worldsState={teamWorldsState} />
          <details
            className="park-team-disclosure"
            onToggle={(e) => setControlsOpen(e.currentTarget.open)}
          >
            <summary className="park-team-summary">Manage team settings</summary>
            {controlsOpen ? <LiveControls app={app} /> : null}
          </details>
          <Helpers night={app.night} />
        </>
      ) : ready ? (
        <TeamBody app={app} data={ready.data} people={ready.people} setPeople={setPeople} />
      ) : loaded === "failed" ? (
        <section className="park-team-card park-team-empty">
          <h2 className="park-team-h2">Team data is unavailable</h2>
        </section>
      ) : null}
    </Frame>
  );
}

interface BodyProps {
  app: AppCtx;
  data: Loaded;
  people: Member[];
  setPeople: Dispatch<SetStateAction<Member[] | null>>;
}

/** W10: the team page shows a sample, so a role, backup or removal is this page's only and nothing is stored. */
const NOT_SAVED = "This is a sample team, so nothing was saved.";

function TeamBody({ app, data, people, setPeople }: BodyProps) {
  const { team } = data;
  const { toast } = app;
  const part = useStaged(4); // drawn top to bottom, one task each (no long task while pages change)
  const [open, setOpen] = useState<string | null>(null);
  // FR-TEAM-01: worlds handed to the Owner by a removal (page state; the Api has no write yet).
  const [handed, setHanded] = useState<World[] | null>(null);
  const [backups, setBackups] = useState<Backups>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [ruleLog, setRuleLog] = useState<{ key: string; when: string; to: boolean }[]>([]);
  const you = people.find((p) => p.you);

  const pref = app.prefs.backup;
  // prefs.backup is the Ledger's backup for the row the fixture flags as slow.
  const slowId = team.coverage.find((c) => c.slow)?.id;
  const lent =
    typeof pref === "string" && slowId && !backups[slowId]
      ? { ...backups, [slowId]: pref }
      : backups;
  const rows = coverRows(team, data.policy, people, lent);
  const views = memberViews(people, rows, lent, handed ? { ...data, worlds: handed } : data);

  const setRole = (p: Member, role: string) => {
    setPeople((ps) =>
      (ps ?? []).map((q) => (q.id === p.id ? { ...q, role, limit: undefined } : q)),
    );
    toast(
      `${p.name} is now ${role === "Approver" || role === "Owner" ? "an" : "a"} ${role} on this page. ${NOT_SAVED}`,
    );
  };
  const remove = (p: Member) => {
    setPeople((ps) => (ps ?? []).filter((q) => q.id !== p.id));
    const owner = people.find((q) => q.role === "Owner");
    if (owner && !p.pending) setHanded((w) => reassignWorlds(w ?? data.worlds, p.name, owner.name));
    setOpen(null);
    toast(
      p.pending
        ? `Invite cancelled on this page. ${NOT_SAVED}`
        : `${p.name.split(" ")[0]} was removed on this page. ${NOT_SAVED}`,
    );
  };
  const addBackup = (row: CoverRow, id: string) => {
    const who = people.find((p) => p.id === id);
    if (!who) return;
    setBackups((b) => ({ ...b, [row.id]: id }));
    if (row.flagged) app.setPref("backup", id);
    toast(`${who.name} is now a backup for ${row.what.toLowerCase()} on this page. ${NOT_SAVED}`);
  };

  return (
    <>
      <Members
        views={views}
        roles={team.roles}
        open={open}
        onOpen={(id) => setOpen((o) => (o === id ? null : id))}
        onRole={setRole}
        canChange={(p) =>
          !!you &&
          you.role !== null &&
          p.role !== null &&
          canChangeRole({ id: you.id, role: you.role }, { id: p.id, role: p.role })
        }
        onRemove={remove}
        onResend={(p) => toast(`This is a sample team, so no invite was sent again to ${p.email}.`)}
      />
      {part(2) ? (
        <Coverage
          rows={rows}
          owner={team.people.find((p) => p.role === "Owner")?.name.split(" ")[0]}
          flash={Boolean(app.params.focus)}
          onBackup={addBackup}
          onLedger={() => app.go("ledger")}
        />
      ) : null}
      {part(3) ? (
        <div className="park-team-two">
          <RulesCard
            rules={team.rules}
            on={flags}
            art={agentArt(app.night)}
            locked={MUST_ASK_RULES}
            log={ruleLog}
            onToggle={(key, next) => {
              if (MUST_ASK_RULES.includes(key) && !next) return;
              setFlags((f) => ({ ...f, [key]: next }));
              const when = team.rules.find((r) => r[0] === key)?.[1] ?? key;
              setRuleLog((l) => [...l, { key, when, to: next }]);
            }}
          />
          {part(4) ? <MatrixCard team={team} /> : null}
        </div>
      ) : null}
    </>
  );
}

/** The owner settings view supplements the people directory; failures do not hide the directory. */
function LiveControls({ app }: { app: AppCtx }) {
  const lt = useLiveTeam(useParkApi());
  return (
    <>
      {lt.state.phase === "ready" ? <LiveInvite live={lt} toast={app.toast} /> : null}
      <StatusLine text={lt.note} />
      {lt.state.phase === "ready" ? (
        <LiveBody live={lt} view={lt.state.view} toast={app.toast} />
      ) : lt.state.phase === "error" ? (
        <p className="park-team-intro">{lt.state.text}</p>
      ) : lt.state.phase === "fixture" ? (
        <p>Not connected yet</p>
      ) : null}
    </>
  );
}
function LiveControlsPage({ app }: { app: AppCtx }) {
  return (
    <Frame>
      <Top />
      <section className="park-team-card park-team-empty">
        <h2 className="park-team-h2">Team data is unavailable</h2>
      </section>
      <LiveControls app={app} />
    </Frame>
  );
}
